import json
import logging
import os
from functools import lru_cache
from typing import Any, Optional

import boto3
from botocore.config import Config
# noinspection PyUnresolvedReferences
from google.auth.exceptions import RefreshError
# noinspection PyUnresolvedReferences
from google.auth.transport.requests import Request
# noinspection PyUnresolvedReferences
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import Settings

logger = logging.getLogger(__name__)

_AWS_CONFIG = Config(
    connect_timeout=3,
    read_timeout=5,
    retries={"total_max_attempts": 2, "mode": "standard"},
)

@lru_cache(maxsize=1)
def _get_secrets_client() -> Any:
    """Cria o cliente somente quando o Secrets Manager for realmente usado."""
    return boto3.client("secretsmanager", config=_AWS_CONFIG)


class GmailAuthenticator:
    """
    Responsável exclusivamente pela autenticação OAuth2 com a Gmail API.

    Princípio SRP: esta classe faz apenas autenticação.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate(self) -> Any:
        """
        Realiza a autenticação OAuth2 e retorna o serviço autenticado da Gmail API.

        Returns:
            Serviço autenticado da Gmail API pronto para uso.

        Raises:
            FileNotFoundError: Se o arquivo de credenciais não for encontrado.
        """
        creds: Optional[Credentials] = self._load_cached_token()

        if not creds or not creds.valid:
            logger.info("Token inválido ou ausente — iniciando processo de autenticação.")
            creds = self._refresh_or_login(creds)
            self._save_token(creds)
        else:
            logger.info("Token válido encontrado em cache.")

        return build("gmail", "v1", credentials=creds)

    def _load_cached_token(self) -> Optional[Credentials]:
        """Carrega o token do Secrets Manager ou do arquivo local."""
        if self._settings.gmail_oauth_secret_arn:
            logger.debug("Carregando credenciais OAuth2 do Secrets Manager.")
            return self._load_secret_credentials()

        if os.path.exists(self._settings.token_file):
            logger.debug("Token encontrado em: %s", self._settings.token_file)
            return Credentials.from_authorized_user_file(
                self._settings.token_file,
                list(self._settings.gmail_scopes),
            )
        logger.debug("Ficheiro de token não encontrado: %s", self._settings.token_file)
        return None

    def _load_secret_credentials(self) -> Credentials:
        """Carrega e valida as credenciais OAuth2 armazenadas no segredo AWS."""
        response = _get_secrets_client().get_secret_value(
            SecretId=self._settings.gmail_oauth_secret_arn
        )
        try:
            token_info = json.loads(response["SecretString"])
            creds = Credentials.from_authorized_user_info(
                token_info,
                list(self._settings.gmail_scopes),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RefreshError(
                "O segredo OAuth2 do Gmail é inválido. "
                "Refaça o consentimento local e atualize o segredo."
            ) from exc

        if not creds.refresh_token:
            raise RefreshError(
                "O segredo OAuth2 do Gmail não contém um refresh_token válido. "
                "Refaça o consentimento local e atualize o segredo."
            )
        return creds

    def _refresh_or_login(self, creds: Optional[Credentials]) -> Credentials:
        """Renova o token expirado ou solicita novo login ao utilizador."""
        if creds and creds.expired and creds.refresh_token:
            logger.info("Token expirado — renovando via refresh_token.")
            creds.refresh(Request())
            return creds

        if self._settings.gmail_oauth_secret_arn:
            raise RefreshError(
                "As credenciais OAuth2 do Gmail armazenadas na AWS não podem ser "
                "renovadas. Refaça o consentimento local e atualize o segredo."
            )

        if not os.path.exists(self._settings.credentials_file):
            raise FileNotFoundError(
                f"Arquivo '{self._settings.credentials_file}' não encontrado.\n"
                "Baixe as credenciais OAuth2 em https://console.cloud.google.com/ "
                f"e salve como '{self._settings.credentials_file}'."
            )

        logger.info("Iniciando fluxo de login OAuth2 (browser).")
        flow = InstalledAppFlow.from_client_secrets_file(
            self._settings.credentials_file,
            list(self._settings.gmail_scopes),
        )
        return flow.run_local_server(port=0)

    def _save_token(self, creds: Credentials) -> None:
        """Persiste o token em disco para reutilização futura."""
        if self._settings.gmail_oauth_secret_arn:
            logger.debug("Token renovado mantido apenas em memória na AWS.")
            return

        with open(self._settings.token_file, "w") as token_file:
            token_file.write(creds.to_json())
        logger.debug("Token gravado em: %s", self._settings.token_file)
