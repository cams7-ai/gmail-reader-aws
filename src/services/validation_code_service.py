import asyncio
import logging
import re
from time import monotonic
from typing import Optional, Tuple

from config import Settings
from domain import EmailMessage
from repositories import GmailRepository

logger = logging.getLogger(__name__)

class ValidationCodeTimeoutError(Exception):
    """Erro lançado quando nenhuma nova mensagem com código chega no tempo limite."""


class ValidationCodeService:
    """
    Serviço de negócio responsável por localizar e extrair o código de validação.

    Princípio SRP: responsável apenas pela lógica de negócio de extração do código.
    Princípio DIP: depende de GmailRepository, não da implementação concreta.
    """

    def __init__(self, repository: GmailRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def get_validation_code(self) -> str:
        """
        Registra o timestamp do último e-mail recebido e aguarda uma nova
        mensagem correspondente com código de validação.

        Returns:
            O código numérico como string.

        Raises:
            ValidationCodeTimeoutError: quando nenhuma nova mensagem com código
            chega dentro do tempo limite configurado.
        """
        last_received_timestamp = self._get_latest_received_timestamp()
        logger.info(
            "Último timestamp de e-mail recebido antes da espera: %d.",
            last_received_timestamp,
        )
        logger.info(
            "Aguardando até %d segundo(s) por uma nova mensagem com código.",
            self._settings.wait_timeout_seconds,
        )

        deadline = monotonic() + self._settings.wait_timeout_seconds
        last_seen_validation_message_id = None
        while True:
            code, last_seen_validation_message_id = self._find_new_validation_code(
                last_received_timestamp,
                last_seen_validation_message_id,
            )
            if code:
                logger.info("Código de validação encontrado.")
                return code

            remaining_seconds = deadline - monotonic()
            if remaining_seconds <= 0:
                break

            logger.info(
                "Nenhuma nova mensagem com código encontrada. "
                "Nova busca em até 1 segundo. Tempo restante: %.3f segundo(s).",
                remaining_seconds,
            )
            await asyncio.sleep(min(1, remaining_seconds))

        message = (
            "Nenhuma nova mensagem com código de validação foi recebida "
            "dentro do tempo limite configurado."
        )
        logger.warning(message)
        raise ValidationCodeTimeoutError(message)

    def _get_latest_received_timestamp(self) -> int:
        """Obtém o timestamp do último e-mail recebido antes da espera."""
        message_ids = self._repository.list_message_ids(query="", limit=1)
        if not message_ids:
            logger.info("Nenhum e-mail existente encontrado; usando timestamp inicial 0.")
            return 0
        return self._repository.get_message_metadata(message_ids[0]).received_timestamp_ms

    def _find_new_validation_code(
        self,
        after_timestamp_ms: int,
        last_seen_message_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Busca uma nova mensagem correspondente e retorna o código encontrado."""
        logger.info(
            "Buscando nova mensagem de '%s' com assunto '%s'.",
            self._settings.sender_email,
            self._settings.subject_filter,
        )
        validation_query = self._build_validation_query()
        latest_message_ids = self._repository.list_message_ids(
            query=validation_query,
            limit=1,
        )
        if not latest_message_ids:
            return None, last_seen_message_id

        latest_message_id = latest_message_ids[0]
        if latest_message_id == last_seen_message_id:
            return None, last_seen_message_id

        latest_message = self._repository.get_message_metadata(latest_message_id)
        if not self._matches_configured_filters(latest_message):
            return None, latest_message_id
        if latest_message.received_timestamp_ms <= after_timestamp_ms:
            return None, latest_message_id

        candidate_ids = self._repository.list_message_ids(
            query=validation_query,
            limit=5,
        )
        for candidate_id in candidate_ids:
            message = (
                latest_message
                if candidate_id == latest_message.id
                else self._repository.get_message_metadata(candidate_id)
            )
            if not self._matches_configured_filters(message):
                continue
            if message.received_timestamp_ms <= after_timestamp_ms:
                continue

            full_message = self._repository.get_message(message.id)
            code = self._extract_code(full_message.body)
            if code:
                return code, latest_message_id
            logger.warning("Nova mensagem encontrada, mas o REGEX não encontrou o código.")

        return None, latest_message_id

    def _build_validation_query(self) -> str:
        """Monta a query usada para localizar mensagens de validação."""
        return (
            f"from:{self._settings.sender_email} "
            f"subject:{self._settings.subject_filter}"
        )

    def _matches_configured_filters(self, message: EmailMessage) -> bool:
        """Confirma remetente e assunto depois da busca da Gmail API."""
        return (
            message.contains_sender(self._settings.sender_email)
            and message.contains_subject(self._settings.subject_filter)
        )

    def _extract_code(self, body: str) -> Optional[str]:
        """Aplica o REGEX configurado no corpo do e-mail e retorna apenas os dígitos."""
        match = re.search(self._settings.activation_code_regex, body)
        if match:
            digits = re.search(r"\d+", match.group())
            if digits:
                return digits.group()
        return None
