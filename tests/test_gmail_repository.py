"""
Testes para GmailRepository.

As mensagens de e-mail são criadas usando o módulo email da stdlib Python,
serializadas com as_bytes() e codificadas em base64 urlsafe — replicando
exactamente o formato "raw" devolvido pela Gmail API.
"""
import base64
import email
from email import encoders, policy as email_policy
from email.message import EmailMessage as ModernEmailMessage
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock

import pytest

from domain import EmailMessage
from repositories.gmail_repository import GmailRepository

# ── helpers ───────────────────────────────────────────────────────────────────

def _b64(msg_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(msg_bytes).decode("ASCII")


def _simple_raw(
    from_addr="sender@test.com",
    to_addr="me@test.com",
    subject="Test Subject",
    date="Mon, 1 Jan 2024 00:00:00 +0000",
    body="Hello plain body",
) -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = date
    return _b64(msg.as_bytes())


def _multipart_raw(
    from_addr="sender@test.com",
    to_addr="me@test.com",
    subject="Test",
    date="Mon, 1 Jan 2024 00:00:00 +0000",
    plain_body=None,
    html_body=None,
    plain_first=True,
) -> str:
    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = date
    parts = []
    if plain_body:
        parts.append(MIMEText(plain_body, "plain", "utf-8"))
    if html_body:
        parts.append(MIMEText(html_body, "html", "utf-8"))
    if not plain_first:
        parts.reverse()
    for part in parts:
        msg.attach(part)
    return _b64(msg.as_bytes())


def _attachment_only_raw() -> str:
    """Multipart com apenas um attachment (sem corpo de texto)."""
    msg = MIMEMultipart()
    msg["From"] = "s@t.com"
    msg["To"] = "m@t.com"
    msg["Subject"] = "Attach only"
    msg["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
    att = MIMEBase("application", "octet-stream")
    att.set_payload(b"fake pdf bytes")
    encoders.encode_base64(att)
    att.add_header("Content-Disposition", 'attachment; filename="file.pdf"')
    msg.attach(att)
    return _b64(msg.as_bytes())


def _plain_attachment_plus_html_raw() -> str:
    """text/plain como attachment + text/html não-attachment → devolve HTML."""
    msg = MIMEMultipart("mixed")
    msg["From"] = "s@t.com"
    msg["To"] = "m@t.com"
    msg["Subject"] = "Mixed"
    msg["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
    plain_att = MIMEText("Plain as attachment", "plain", "utf-8")
    plain_att.add_header("Content-Disposition", 'attachment; filename="body.txt"')
    msg.attach(plain_att)
    msg.attach(MIMEText("<html>HTML fallback</html>", "html", "utf-8"))
    return _b64(msg.as_bytes())


def _double_html_raw() -> str:
    """Dois partes text/html — o segundo deve ser ignorado (not body = False)."""
    msg = MIMEMultipart("alternative")
    msg["From"] = "s@t.com"
    msg["To"] = "m@t.com"
    msg["Subject"] = "Double HTML"
    msg["Date"] = "Mon, 1 Jan 2024 00:00:00 +0000"
    msg.attach(MIMEText("<html>First HTML</html>", "html", "utf-8"))
    msg.attach(MIMEText("<html>Second HTML</html>", "html", "utf-8"))
    return _b64(msg.as_bytes())


def _metadata_response(
    from_addr="sender@test.com",
    to_addr="me@test.com",
    subject="Test Subject",
    date="Mon, 1 Jan 2024 00:00:00 +0000",
    internal_date="1704067200000",
) -> dict:
    return {
        "payload": {
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "To", "value": to_addr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ]
        },
        "internalDate": internal_date,
    }


@pytest.fixture
def mock_service():
    return MagicMock()


# ── list_messages ─────────────────────────────────────────────────────────────

class TestListMessages:
    def test_returns_list_of_email_messages(self, mock_service):
        raw = _simple_raw()
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}]
        }
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        result = repo.list_messages(query="from:test", limit=5)

        assert len(result) == 2
        assert all(isinstance(m, EmailMessage) for m in result)

    def test_returns_empty_list_when_api_has_no_messages(self, mock_service):
        mock_service.users().messages().list().execute.return_value = {}

        repo = GmailRepository(mock_service)
        result = repo.list_messages(query="from:test", limit=5)

        assert result == []

    def test_passes_correct_params_to_api(self, mock_service):
        mock_service.users().messages().list().execute.return_value = {}

        repo = GmailRepository(mock_service)
        repo.list_messages(query="from:sender@test.com", limit=3)

        mock_service.users().messages().list.assert_called_with(
            userId="me", maxResults=3, q="from:sender@test.com"
        )
        mock_service.users().messages().list().execute.assert_called_with(num_retries=3)

    def test_returns_metadata_when_include_body_is_false(self, mock_service):
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}]
        }
        mock_service.users().messages().get().execute.return_value = _metadata_response()

        repo = GmailRepository(mock_service)
        result = repo.list_messages(query="from:test", limit=1, include_body=False)

        assert len(result) == 1
        assert result[0].id == "msg1"
        assert result[0].sender == "sender@test.com"
        assert result[0].subject == "Test Subject"
        assert result[0].body == ""
        assert result[0].received_timestamp_ms == 1704067200000
        mock_service.users().messages().get.assert_called_with(
            userId="me",
            id="msg1",
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        )
        mock_service.users().messages().get().execute.assert_called_with(num_retries=3)


# ── get_message ───────────────────────────────────────────────────────────────

class TestGetMessage:
    def test_plain_text_email_fields_are_parsed(self, mock_service):
        raw = _simple_raw(
            from_addr="sender@test.com",
            to_addr="me@test.com",
            subject="Test Subject",
            date="Mon, 1 Jan 2024 00:00:00 +0000",
            body="Hello plain body",
        )
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg123")

        assert msg.id == "msg123"
        assert msg.sender == "sender@test.com"
        assert msg.recipient == "me@test.com"
        assert msg.subject == "Test Subject"
        assert "Hello plain body" in msg.body
        assert msg.received_timestamp_ms == 0
        mock_service.users().messages().get().execute.assert_called_with(num_retries=3)

    def test_internal_date_is_parsed_as_received_timestamp(self, mock_service):
        raw = _simple_raw()
        mock_service.users().messages().get().execute.return_value = {
            "raw": raw,
            "internalDate": "1704067200000",
        }

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert msg.received_timestamp_ms == 1704067200000

    def test_metadata_fields_are_parsed(self, mock_service):
        mock_service.users().messages().get().execute.return_value = _metadata_response(
            from_addr="Caixa <logincaixa@caixa.gov.br>",
            to_addr="me@test.com",
            subject="Código de Validação",
            date="Tue, 2 Jan 2024 00:00:00 +0000",
            internal_date="1704153600000",
        )

        repo = GmailRepository(mock_service)
        msg = repo.get_message_metadata("msg1")

        assert msg.id == "msg1"
        assert msg.sender == "Caixa <logincaixa@caixa.gov.br>"
        assert msg.recipient == "me@test.com"
        assert msg.subject == "Código de Validação"
        assert msg.date == "Tue, 2 Jan 2024 00:00:00 +0000"
        assert msg.body == ""
        assert msg.received_timestamp_ms == 1704153600000

    def test_multipart_prefers_plain_text_over_html(self, mock_service):
        raw = _multipart_raw(plain_body="Plain body text", html_body="<html>HTML</html>")
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert "Plain body text" in msg.body
        assert "[HTML]" not in msg.body

    def test_multipart_html_only_returns_html_with_prefix(self, mock_service):
        raw = _multipart_raw(html_body="<html>HTML only</html>")
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert "[HTML]" in msg.body
        assert "HTML only" in msg.body

    def test_multipart_html_before_plain_still_returns_plain(self, mock_service):
        raw = _multipart_raw(
            plain_body="Plain wins", html_body="<html>HTML</html>", plain_first=False
        )
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert "Plain wins" in msg.body
        assert "[HTML]" not in msg.body

    def test_attachment_only_returns_placeholder(self, mock_service):
        raw = _attachment_only_raw()
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert msg.body == "(sem conteúdo)"

    def test_plain_attachment_plus_html_returns_html(self, mock_service):
        """text/plain marcado como attachment deve ser ignorado; HTML é usado."""
        raw = _plain_attachment_plus_html_raw()
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert "[HTML]" in msg.body
        assert "HTML fallback" in msg.body

    def test_double_html_uses_first_and_ignores_second(self, mock_service):
        """Segundo part HTML é ignorado porque body já foi preenchido (not body = False)."""
        raw = _double_html_raw()
        mock_service.users().messages().get().execute.return_value = {"raw": raw}

        repo = GmailRepository(mock_service)
        msg = repo.get_message("msg1")

        assert "[HTML]" in msg.body
        assert "First HTML" in msg.body


# ── _extract_body (static) ────────────────────────────────────────────────────

class TestExtractBody:
    """Testa _extract_body directamente para garantir cobertura de todos os ramos."""

    @staticmethod
    def _parse(raw: str):
        raw_bytes = base64.urlsafe_b64decode(raw.encode("ASCII"))
        return email.message_from_bytes(raw_bytes, policy=email_policy.default)

    def test_simple_non_multipart_message(self):
        parsed = self._parse(_simple_raw(body="Direct body"))
        body = GmailRepository._extract_body(parsed)
        assert "Direct body" in body

    def test_multipart_plain_and_html(self):
        parsed = self._parse(_multipart_raw(plain_body="Plain", html_body="<html>H</html>"))
        body = GmailRepository._extract_body(parsed)
        assert "Plain" in body

    def test_multipart_html_only(self):
        parsed = self._parse(_multipart_raw(html_body="<html>HTML</html>"))
        body = GmailRepository._extract_body(parsed)
        assert "[HTML]" in body

    def test_multipart_attachment_only_returns_empty_string(self):
        parsed = self._parse(_attachment_only_raw())
        body = GmailRepository._extract_body(parsed)
        assert body == ""

    def test_double_html_second_is_skipped(self):
        parsed = self._parse(_double_html_raw())
        body = GmailRepository._extract_body(parsed)
        assert "[HTML]" in body
        assert "First HTML" in body


