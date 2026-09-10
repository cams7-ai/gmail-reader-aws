import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from config import Settings
from domain import EmailMessage
from repositories import GmailRepository
from services import (
    ValidationCodeService,
    ValidationCodeTimeoutError,
)

@pytest.fixture
def settings():
    return Settings(
        sender_email="logincaixa@caixa.gov.br",
        subject_filter="Código de Validação",
        activation_code_regex=r"Código de ativação: \d+",
        wait_timeout_seconds=2,
    )


@pytest.fixture
def mock_repo():
    return MagicMock(spec=GmailRepository)


def _make_email(
    *,
    id="msg1",
    sender="Caixa <logincaixa@caixa.gov.br>",
    subject="Código de Validação",
    body="Código de ativação: 123456",
    received_timestamp_ms=1000,
):
    return EmailMessage(
        id=id,
        sender=sender,
        recipient="me@test.com",
        subject=subject,
        date="Mon, 1 Jan 2024 00:00:00 +0000",
        body=body,
        received_timestamp_ms=received_timestamp_ms,
    )


def _run(coro):
    return asyncio.run(coro)


class TestGetValidationCode:
    def test_returns_code_when_new_email_found_immediately(self, settings, mock_repo):
        old_email = _make_email(id="old", received_timestamp_ms=1000)
        new_email = _make_email(id="new", received_timestamp_ms=2000)
        mock_repo.list_message_ids.side_effect = [
            ["old"],
            ["new"],
            ["old", "new"],
        ]
        mock_repo.get_message_metadata.side_effect = [old_email, new_email, old_email]
        mock_repo.get_message.return_value = new_email

        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch(
                "services.validation_code_service.monotonic",
                side_effect=[0, 1],
            ),
        ):
            service = ValidationCodeService(mock_repo, settings)
            result = _run(service.get_validation_code())

        assert result == "123456"
        mock_sleep.assert_not_awaited()

    def test_ignores_existing_email_and_waits_for_new_one(self, settings, mock_repo):
        old_email = _make_email(id="old", received_timestamp_ms=1000)
        new_email = _make_email(id="new", received_timestamp_ms=2000)
        mock_repo.list_message_ids.side_effect = [
            ["old"],
            ["old"],
            ["new"],
            ["new"],
        ]
        mock_repo.get_message_metadata.side_effect = [old_email, old_email, new_email]
        mock_repo.get_message.return_value = new_email

        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch(
                "services.validation_code_service.monotonic",
                side_effect=[0, 0, 1, 2],
            ),
        ):
            service = ValidationCodeService(mock_repo, settings)
            result = _run(service.get_validation_code())

        assert result == "123456"
        mock_sleep.assert_awaited_once_with(1)

    def test_skips_non_matching_sender_and_subject(self, settings, mock_repo):
        old_email = _make_email(id="old", received_timestamp_ms=1000)
        wrong_sender = _make_email(
            id="wrong-sender",
            sender="other@email.com",
            received_timestamp_ms=2000,
        )
        wrong_subject = _make_email(
            id="wrong-subject",
            subject="Outro Assunto",
            received_timestamp_ms=3000,
        )
        matching = _make_email(id="matching", received_timestamp_ms=4000)
        mock_repo.list_message_ids.side_effect = [
            ["old"],
            ["matching"],
            ["wrong-sender", "wrong-subject", "matching"],
        ]
        mock_repo.get_message_metadata.side_effect = [
            old_email,
            matching,
            wrong_sender,
            wrong_subject,
        ]
        mock_repo.get_message.return_value = matching

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            service = ValidationCodeService(mock_repo, settings)
            result = _run(service.get_validation_code())

        assert result == "123456"
        mock_sleep.assert_not_awaited()

    def test_continues_when_new_message_has_no_code(self, settings, mock_repo, caplog):
        old_email = _make_email(id="old", received_timestamp_ms=1000)
        no_code = _make_email(
            id="no-code",
            body="Mensagem sem código",
            received_timestamp_ms=2000,
        )
        with_code = _make_email(id="with-code", received_timestamp_ms=3000)
        mock_repo.list_message_ids.side_effect = [
            ["old"],
            ["no-code"],
            ["no-code", "with-code"],
        ]
        mock_repo.get_message_metadata.side_effect = [old_email, no_code, with_code]
        mock_repo.get_message.side_effect = [no_code, with_code]
        caplog.set_level(logging.WARNING, logger="services.validation_code_service")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            service = ValidationCodeService(mock_repo, settings)
            result = _run(service.get_validation_code())

        assert result == "123456"
        assert any(
            "REGEX não encontrou o código" in record.message
            for record in caplog.records
        )

    def test_raises_timeout_when_no_new_message_with_code_arrives(self, settings, mock_repo):
        mock_repo.list_message_ids.side_effect = [[], [], [], []]

        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch(
                "services.validation_code_service.monotonic",
                side_effect=[0, 0, 1, 2],
            ),
        ):
            service = ValidationCodeService(mock_repo, settings)
            with pytest.raises(ValidationCodeTimeoutError) as exc_info:
                _run(service.get_validation_code())

        assert "Nenhuma nova mensagem com código de validação" in str(exc_info.value)
        assert mock_sleep.await_count == 2
        mock_sleep.assert_awaited_with(1)
        mock_repo.get_message.assert_not_called()

    def test_gmail_latency_consumes_the_wait_budget(self, settings, mock_repo):
        mock_repo.list_message_ids.side_effect = [[], []]

        with (
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch(
                "services.validation_code_service.monotonic",
                side_effect=[10, 13],
            ),
        ):
            service = ValidationCodeService(mock_repo, settings)
            with pytest.raises(ValidationCodeTimeoutError):
                _run(service.get_validation_code())

        mock_sleep.assert_not_awaited()
        assert mock_repo.list_message_ids.call_count == 2


class TestFindNewValidationCode:
    def test_returns_none_when_latest_metadata_does_not_match_filters(
        self,
        settings,
        mock_repo,
    ):
        wrong_sender = _make_email(
            id="wrong-sender",
            sender="other@email.com",
            received_timestamp_ms=2000,
        )
        mock_repo.list_message_ids.return_value = ["wrong-sender"]
        mock_repo.get_message_metadata.return_value = wrong_sender

        service = ValidationCodeService(mock_repo, settings)
        result = service._find_new_validation_code(after_timestamp_ms=1000)

        assert result == (None, "wrong-sender")
        mock_repo.get_message.assert_not_called()

    def test_returns_none_when_new_message_has_no_code(self, settings, mock_repo):
        no_code = _make_email(
            id="no-code",
            body="Mensagem sem código",
            received_timestamp_ms=2000,
        )
        mock_repo.list_message_ids.side_effect = [["no-code"], ["no-code"]]
        mock_repo.get_message_metadata.return_value = no_code
        mock_repo.get_message.return_value = no_code

        service = ValidationCodeService(mock_repo, settings)
        result = service._find_new_validation_code(after_timestamp_ms=1000)

        assert result == (None, "no-code")

    def test_skips_metadata_when_latest_id_was_already_seen(self, settings, mock_repo):
        mock_repo.list_message_ids.return_value = ["same-id"]

        service = ValidationCodeService(mock_repo, settings)
        result = service._find_new_validation_code(
            after_timestamp_ms=1000,
            last_seen_message_id="same-id",
        )

        assert result == (None, "same-id")
        mock_repo.get_message_metadata.assert_not_called()
        mock_repo.get_message.assert_not_called()


class TestPolling:
    def test_logs_remaining_seconds(self, settings, mock_repo, caplog):
        mock_repo.list_message_ids.side_effect = [[], [], [], []]
        caplog.set_level(logging.INFO, logger="services.validation_code_service")

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "services.validation_code_service.monotonic",
                side_effect=[0, 0, 1, 2],
            ),
        ):
            service = ValidationCodeService(mock_repo, settings)
            with pytest.raises(ValidationCodeTimeoutError):
                _run(service.get_validation_code())

        messages = [record.message for record in caplog.records]
        assert any("Tempo restante: 2.000 segundo(s)" in message for message in messages)
        assert any("Tempo restante: 1.000 segundo(s)" in message for message in messages)

    def test_builds_expected_queries(self, settings, mock_repo):
        mock_repo.list_message_ids.side_effect = [[], [], [], []]

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "services.validation_code_service.monotonic",
                side_effect=[0, 0, 1, 2],
            ),
        ):
            service = ValidationCodeService(mock_repo, settings)
            with pytest.raises(ValidationCodeTimeoutError):
                _run(service.get_validation_code())

        expected_query = f"from:{settings.sender_email} subject:{settings.subject_filter}"
        mock_repo.list_message_ids.assert_has_calls(
            [
                call(query="", limit=1),
                call(query=expected_query, limit=1),
                call(query=expected_query, limit=1),
                call(query=expected_query, limit=1),
            ]
        )


class TestExtractCode:
    def test_extracts_digits_from_matching_pattern(self, settings, mock_repo):
        service = ValidationCodeService(mock_repo, settings)
        result = service._extract_code("Código de ativação: 987654")
        assert result == "987654"

    def test_returns_none_when_pattern_not_found(self, settings, mock_repo):
        service = ValidationCodeService(mock_repo, settings)
        result = service._extract_code("Nenhum código aqui")
        assert result is None

    def test_returns_none_when_match_has_no_digits(self, mock_repo):
        settings_no_digits = Settings(
            activation_code_regex=r"Code: [a-z]+",
            wait_timeout_seconds=2,
        )
        service = ValidationCodeService(mock_repo, settings_no_digits)
        result = service._extract_code("Code: abc")
        assert result is None
