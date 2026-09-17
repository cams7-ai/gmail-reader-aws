import json
from dataclasses import replace
from unittest.mock import MagicMock, mock_open, patch

import pytest
from google.auth.exceptions import RefreshError

from config import Settings
from infra import GmailAuthenticator
from infra.gmail_auth import _get_secrets_client


@pytest.fixture(autouse=True)
def clear_secrets_client_cache():
    _get_secrets_client.cache_clear()
    yield
    _get_secrets_client.cache_clear()


def test_secrets_client_is_created_once_with_aws_config():
    client = MagicMock()
    with patch("infra.gmail_auth.boto3.client", return_value=client) as client_factory:
        assert _get_secrets_client() is client
        assert _get_secrets_client() is client

    client_factory.assert_called_once_with(
        "secretsmanager",
        config=pytest.importorskip("infra.gmail_auth")._AWS_CONFIG,
    )

@pytest.fixture
def settings():
    return Settings(
        credentials_file="GmailAPI/credentials.json",
        token_file="GmailAPI/token.json",
        gmail_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
    )


@pytest.fixture
def aws_settings(settings):
    return replace(
        settings,
        gmail_oauth_secret_arn=(
            "arn:aws:secretsmanager:sa-east-1:123456789012:"
            "secret:gmail-reader/google-oauth-token"
        ),
    )


# ── _load_cached_token ────────────────────────────────────────────────────────

class TestLoadCachedToken:
    def test_secret_takes_precedence_over_local_file(self, aws_settings):
        mock_creds = MagicMock()
        with (
            patch("infra.gmail_auth.os.path.exists") as exists,
            patch.object(
                GmailAuthenticator,
                "_load_secret_credentials",
                return_value=mock_creds,
            ) as load_secret,
        ):
            result = GmailAuthenticator(aws_settings)._load_cached_token()

        assert result is mock_creds
        load_secret.assert_called_once_with()
        exists.assert_not_called()

    def test_loads_credentials_from_secret(self, aws_settings):
        token_info = {
            "token": "access-token",
            "refresh_token": "refresh-token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        mock_creds = MagicMock(refresh_token="refresh-token")
        with (
            patch("infra.gmail_auth._get_secrets_client") as get_secrets_client,
            patch(
                "infra.gmail_auth.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ) as from_info,
        ):
            secrets_client = get_secrets_client.return_value
            secrets_client.get_secret_value.return_value = {
                "SecretString": json.dumps(token_info)
            }
            result = GmailAuthenticator(aws_settings)._load_secret_credentials()

        assert result is mock_creds
        secrets_client.get_secret_value.assert_called_once_with(
            SecretId=aws_settings.gmail_oauth_secret_arn
        )
        from_info.assert_called_once_with(token_info, list(aws_settings.gmail_scopes))

    def test_rejects_invalid_secret_json(self, aws_settings):
        with patch("infra.gmail_auth._get_secrets_client") as get_secrets_client:
            secrets_client = get_secrets_client.return_value
            secrets_client.get_secret_value.return_value = {"SecretString": "not-json"}

            with pytest.raises(RefreshError, match="segredo OAuth2 do Gmail é inválido"):
                GmailAuthenticator(aws_settings)._load_secret_credentials()

    def test_rejects_secret_without_refresh_token(self, aws_settings):
        mock_creds = MagicMock(refresh_token=None)
        with (
            patch("infra.gmail_auth._get_secrets_client") as get_secrets_client,
            patch(
                "infra.gmail_auth.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
        ):
            secrets_client = get_secrets_client.return_value
            secrets_client.get_secret_value.return_value = {"SecretString": "{}"}

            with pytest.raises(RefreshError, match="refresh_token válido"):
                GmailAuthenticator(aws_settings)._load_secret_credentials()

    def test_returns_none_when_token_file_does_not_exist(self, settings):
        with patch("infra.gmail_auth.os.path.exists", return_value=False):
            auth = GmailAuthenticator(settings)
            assert auth._load_cached_token() is None

    def test_returns_credentials_when_token_file_exists(self, settings):
        mock_creds = MagicMock()
        with patch("infra.gmail_auth.os.path.exists", return_value=True), \
             patch("infra.gmail_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
            auth = GmailAuthenticator(settings)
            result = auth._load_cached_token()
            assert result is mock_creds


# ── _refresh_or_login ─────────────────────────────────────────────────────────

class TestRefreshOrLogin:
    def test_refreshes_expired_credentials(self, settings):
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "token"

        with patch("infra.gmail_auth.Request") as mock_request_cls:
            auth = GmailAuthenticator(settings)
            result = auth._refresh_or_login(mock_creds)

            mock_creds.refresh.assert_called_once_with(mock_request_cls.return_value)
            assert result is mock_creds

    def test_raises_file_not_found_when_credentials_file_missing(self, settings):
        with patch("infra.gmail_auth.os.path.exists", return_value=False):
            auth = GmailAuthenticator(settings)
            with pytest.raises(FileNotFoundError, match=settings.credentials_file):
                auth._refresh_or_login(None)

    def test_never_starts_interactive_login_in_aws(self, aws_settings):
        with patch(
            "infra.gmail_auth.InstalledAppFlow.from_client_secrets_file"
        ) as flow:
            with pytest.raises(RefreshError, match="não podem ser renovadas"):
                GmailAuthenticator(aws_settings)._refresh_or_login(None)

        flow.assert_not_called()

    def test_runs_local_server_when_credentials_file_exists(self, settings):
        mock_creds = MagicMock()
        with patch("infra.gmail_auth.os.path.exists", return_value=True), \
             patch("infra.gmail_auth.InstalledAppFlow.from_client_secrets_file") as mock_flow_cls:
            mock_flow_cls.return_value.run_local_server.return_value = mock_creds

            auth = GmailAuthenticator(settings)
            result = auth._refresh_or_login(None)

            mock_flow_cls.assert_called_once_with(
                settings.credentials_file,
                list(settings.gmail_scopes),
            )
            mock_flow_cls.return_value.run_local_server.assert_called_once_with(port=0)
            assert result is mock_creds


# ── _save_token ───────────────────────────────────────────────────────────────

class TestSaveToken:
    def test_does_not_write_token_in_aws(self, aws_settings):
        with patch("builtins.open", mock_open()) as token_file:
            GmailAuthenticator(aws_settings)._save_token(MagicMock())

        token_file.assert_not_called()

    def test_writes_credentials_json_to_token_file(self, settings):
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"access_token": "abc"}'

        m = mock_open()
        with patch("builtins.open", m):
            auth = GmailAuthenticator(settings)
            auth._save_token(mock_creds)

        m.assert_called_once_with(settings.token_file, "w")
        m().write.assert_called_once_with('{"access_token": "abc"}')


# ── authenticate ──────────────────────────────────────────────────────────────

class TestAuthenticate:
    def test_uses_valid_cached_token_without_refreshing(self, settings):
        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch("infra.gmail_auth.os.path.exists", return_value=True), \
             patch("infra.gmail_auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("infra.gmail_auth.build") as mock_build:
            auth = GmailAuthenticator(settings)
            result = auth.authenticate()

            mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)
            assert result is mock_build.return_value

    def test_refreshes_expired_token_and_saves(self, settings):
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"

        with patch("infra.gmail_auth.os.path.exists", return_value=True), \
             patch("infra.gmail_auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
             patch("infra.gmail_auth.Request"), \
             patch("infra.gmail_auth.build"), \
             patch("builtins.open", mock_open()):
            auth = GmailAuthenticator(settings)
            auth.authenticate()

            mock_creds.refresh.assert_called_once()
            mock_creds.to_json.assert_called_once()

    def test_runs_login_flow_when_no_token_file(self, settings):
        mock_creds = MagicMock()

        def exists_side_effect(path):
            return path == settings.credentials_file  # token does NOT exist

        with patch("infra.gmail_auth.os.path.exists", side_effect=exists_side_effect), \
             patch("infra.gmail_auth.InstalledAppFlow.from_client_secrets_file") as mock_flow_cls, \
             patch("infra.gmail_auth.build"), \
             patch("builtins.open", mock_open()):
            mock_flow_cls.return_value.run_local_server.return_value = mock_creds

            auth = GmailAuthenticator(settings)
            auth.authenticate()

            mock_flow_cls.return_value.run_local_server.assert_called_once_with(port=0)
            mock_creds.to_json.assert_called_once()
