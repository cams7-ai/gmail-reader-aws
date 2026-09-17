from dataclasses import replace

import pytest

from config import Settings

_ENV_KEYS = [
    "SENDER_EMAIL",
    "SUBJECT_FILTER",
    "ACTIVATION_CODE_REGEX",
    "WAIT_TIMEOUT_SECONDS",
    "GMAIL_OAUTH_SECRET_ARN",
    "CREDENTIALS_FILE",
    "TOKEN_FILE",
]


class TestSettingsDefaults:
    """Verifica que os valores padrão são usados quando as variáveis de ambiente não estão definidas."""

    def test_sender_email_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().sender_email == "logincaixa@caixa.gov.br"

    def test_subject_filter_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().subject_filter == "Código de Validação"

    def test_activation_code_regex_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().activation_code_regex == r"Código de ativação: \d+"

    def test_wait_timeout_seconds_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().wait_timeout_seconds == 15

    def test_credentials_file_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().credentials_file == "GmailAPI/credentials.json"

    def test_gmail_oauth_secret_arn_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().gmail_oauth_secret_arn is None

    def test_token_file_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert Settings().token_file == "GmailAPI/token.json"

    def test_gmail_scopes_default(self, monkeypatch):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert "https://www.googleapis.com/auth/gmail.readonly" in Settings().gmail_scopes


class TestSettingsFromEnv:
    """Verifica que os valores são lidos corretamente das variáveis de ambiente."""

    def test_sender_email_from_env(self, monkeypatch):
        monkeypatch.setenv("SENDER_EMAIL", "custom@email.com")
        assert Settings().sender_email == "custom@email.com"

    def test_subject_filter_from_env(self, monkeypatch):
        monkeypatch.setenv("SUBJECT_FILTER", "Custom Subject")
        assert Settings().subject_filter == "Custom Subject"

    def test_activation_code_regex_from_env(self, monkeypatch):
        monkeypatch.setenv("ACTIVATION_CODE_REGEX", r"Code: \d+")
        assert Settings().activation_code_regex == r"Code: \d+"

    def test_wait_timeout_seconds_from_env(self, monkeypatch):
        monkeypatch.setenv("WAIT_TIMEOUT_SECONDS", "10")
        assert Settings().wait_timeout_seconds == 10

    @pytest.mark.parametrize("value", ["-1", "16"])
    def test_wait_timeout_seconds_outside_supported_range(self, monkeypatch, value):
        monkeypatch.setenv("WAIT_TIMEOUT_SECONDS", value)

        with pytest.raises(ValueError, match="inteiro entre 0 e 15"):
            Settings()

    def test_credentials_file_from_env(self, monkeypatch):
        monkeypatch.setenv("CREDENTIALS_FILE", "custom/creds.json")
        assert Settings().credentials_file == "custom/creds.json"

    def test_gmail_oauth_secret_arn_from_env(self, monkeypatch):
        secret_arn = (
            "arn:aws:secretsmanager:sa-east-1:123456789012:"
            "secret:gmail-reader/google-oauth-token"
        )
        monkeypatch.setenv("GMAIL_OAUTH_SECRET_ARN", secret_arn)
        assert Settings().gmail_oauth_secret_arn == secret_arn

    def test_token_file_from_env(self, monkeypatch):
        monkeypatch.setenv("TOKEN_FILE", "custom/token.json")
        assert Settings().token_file == "custom/token.json"


class TestSettingsFrozen:
    """Verifica que Settings é imutável após a criação."""

    def test_settings_is_frozen(self):
        settings = Settings()
        with pytest.raises(Exception):
            settings.sender_email = "new@email.com"  # type: ignore

    def test_replace_timeout_preserves_gmail_oauth_secret_arn(self):
        secret_arn = (
            "arn:aws:secretsmanager:sa-east-1:123456789012:"
            "secret:gmail-reader/google-oauth-token"
        )
        settings = Settings(gmail_oauth_secret_arn=secret_arn)

        updated = replace(settings, wait_timeout_seconds=15)

        assert updated.wait_timeout_seconds == 15
        assert updated.gmail_oauth_secret_arn == secret_arn
