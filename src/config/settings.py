import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Centraliza todas as configurações da aplicação carregadas das variáveis de ambiente."""

    sender_email: str = field(
        default_factory=lambda: os.getenv("SENDER_EMAIL", "logincaixa@caixa.gov.br")
    )
    subject_filter: str = field(
        default_factory=lambda: os.getenv("SUBJECT_FILTER", "Código de Validação")
    )
    activation_code_regex: str = field(
        default_factory=lambda: os.getenv("ACTIVATION_CODE_REGEX", r"Código de ativação: \d+")
    )
    wait_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("WAIT_TIMEOUT_SECONDS", "15"))
    )
    gmail_oauth_secret_arn: str | None = field(
        default_factory=lambda: os.getenv("GMAIL_OAUTH_SECRET_ARN")
    )
    credentials_file: str = field(
        default_factory=lambda: os.getenv("CREDENTIALS_FILE", "GmailAPI/credentials.json")
    )
    token_file: str = field(
        default_factory=lambda: os.getenv("TOKEN_FILE", "GmailAPI/token.json")
    )
    gmail_scopes: tuple = field(
        default_factory=lambda: ("https://www.googleapis.com/auth/gmail.readonly",)
    )

    def __post_init__(self) -> None:
        if not 0 <= self.wait_timeout_seconds <= 15:
            raise ValueError("WAIT_TIMEOUT_SECONDS deve ser um inteiro entre 0 e 15.")
