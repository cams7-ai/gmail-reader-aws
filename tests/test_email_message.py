import pytest

from domain import EmailMessage

@pytest.fixture
def message():
    return EmailMessage(
        id="msg123",
        sender="Caixa Econômica <logincaixa@caixa.gov.br>",
        recipient="me@gmail.com",
        subject="Código de Validação - Login Caixa",
        date="Mon, 1 Jan 2024 00:00:00 +0000",
        body="Código de ativação: 123456",
    )


class TestEmailMessageContainsSender:
    def test_returns_true_when_email_is_in_sender(self, message):
        assert message.contains_sender("logincaixa@caixa.gov.br") is True

    def test_returns_true_case_insensitive(self, message):
        assert message.contains_sender("LOGINCAIXA@CAIXA.GOV.BR") is True

    def test_returns_false_when_email_not_in_sender(self, message):
        assert message.contains_sender("other@email.com") is False

    def test_returns_false_for_partial_mismatch(self, message):
        assert message.contains_sender("notfound@domain.com") is False


class TestEmailMessageContainsSubject:
    def test_returns_true_when_keyword_is_in_subject(self, message):
        assert message.contains_subject("Código de Validação") is True

    def test_returns_true_case_insensitive(self, message):
        assert message.contains_subject("código de validação") is True

    def test_returns_false_when_keyword_not_in_subject(self, message):
        assert message.contains_subject("Fatura") is False

    def test_returns_false_for_unrelated_keyword(self, message):
        assert message.contains_subject("Boleto") is False


class TestEmailMessageDataclass:
    def test_equality_between_identical_instances(self):
        msg1 = EmailMessage("1", "a@b.com", "c@d.com", "Sub", "Date", "Body")
        msg2 = EmailMessage("1", "a@b.com", "c@d.com", "Sub", "Date", "Body")
        assert msg1 == msg2

    def test_inequality_when_fields_differ(self):
        msg1 = EmailMessage("1", "a@b.com", "c@d.com", "Sub", "Date", "Body")
        msg2 = EmailMessage("2", "a@b.com", "c@d.com", "Sub", "Date", "Body")
        assert msg1 != msg2

    def test_fields_are_correctly_stored(self):
        msg = EmailMessage(
            "id",
            "from@x.com",
            "to@x.com",
            "Subject",
            "Date",
            "Body",
            1704067200000,
        )
        assert msg.id == "id"
        assert msg.sender == "from@x.com"
        assert msg.recipient == "to@x.com"
        assert msg.subject == "Subject"
        assert msg.date == "Date"
        assert msg.body == "Body"
        assert msg.received_timestamp_ms == 1704067200000

    def test_received_timestamp_defaults_to_zero(self):
        msg = EmailMessage("id", "from@x.com", "to@x.com", "Subject", "Date", "Body")

        assert msg.received_timestamp_ms == 0


