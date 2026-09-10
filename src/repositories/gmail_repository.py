import base64
import email
import email.message
import logging
from email import policy as email_policy
from email.message import MIMEPart
from typing import Any, Union

from domain import EmailMessage

logger = logging.getLogger(__name__)

class GmailRepository:
    """
    Implementação do repositório de e-mails usando a Gmail API.

    Princípio SRP: responsável apenas pelo acesso aos dados do Gmail.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def list_message_ids(self, query: str, limit: int = 10) -> list[str]:
        """Lista IDs das mensagens mais recentes que correspondam ao filtro."""
        logger.debug("Listando IDs de mensagens — query='%s', limit=%d", query, limit)
        result = self._service.users().messages().list(
            userId="me",
            maxResults=limit,
            q=query,
        ).execute(num_retries=3)

        raw_messages = result.get("messages", [])
        logger.debug("%d ID(s) de mensagem encontrado(s).", len(raw_messages))
        return [msg["id"] for msg in raw_messages]

    def list_messages(
        self,
        query: str,
        limit: int = 10,
        include_body: bool = True,
    ) -> list[EmailMessage]:
        """Lista e retorna as mensagens mais recentes que correspondam ao filtro."""
        logger.debug(
            "Listando mensagens — query='%s', limit=%d, include_body=%s",
            query,
            limit,
            include_body,
        )
        message_ids = self.list_message_ids(query=query, limit=limit)
        if not include_body:
            return [self.get_message_metadata(message_id) for message_id in message_ids]
        return [self.get_message(message_id) for message_id in message_ids]

    def get_message_metadata(self, message_id: str):
        """Obtém apenas metadados de uma mensagem, sem baixar o corpo."""
        logger.debug("Obtendo metadados da mensagem id=%s", message_id)
        msg_metadata = self._service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ).execute(num_retries=3)
        headers = self._headers_to_dict(msg_metadata.get("payload", {}).get("headers", []))

        return EmailMessage(
            id=message_id,
            sender=headers.get("From", ""),
            recipient=headers.get("To", ""),
            subject=headers.get("Subject", "(sem assunto)"),
            date=headers.get("Date", ""),
            body="",
            received_timestamp_ms=int(msg_metadata.get("internalDate") or 0),
        )

    def get_message(self, message_id: str):
        """Obtém e descodifica o conteúdo completo de uma mensagem."""
        logger.debug("Obtendo mensagem id=%s", message_id)
        msg_raw = self._service.users().messages().get(
            userId="me",
            id=message_id,
            format="raw",
        ).execute(num_retries=3)

        raw_bytes = base64.urlsafe_b64decode(msg_raw["raw"].encode("ASCII"))
        msg = email.message_from_bytes(raw_bytes, policy=email_policy.default)
        body = self._extract_body(msg)

        return EmailMessage(
            id=message_id,
            sender=msg.get("From", ""),
            recipient=msg.get("To", ""),
            subject=msg.get("Subject", "(sem assunto)"),
            date=msg.get("Date", ""),
            body=body.strip() if body else "(sem conteúdo)",
            received_timestamp_ms=int(msg_raw.get("internalDate") or 0),
        )

    @staticmethod
    def _headers_to_dict(headers: list[dict[str, str]]) -> dict[str, str]:
        """Converte headers da Gmail API para dicionário por nome."""
        return {header.get("name", ""): header.get("value", "") for header in headers}

    @staticmethod
    def _extract_body(msg: Union[email.message.Message, MIMEPart]) -> str:
        """Extrai o corpo da mensagem preferindo texto simples sobre HTML."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                mime_part: MIMEPart = part  # type: ignore[assignment]
                if content_type == "text/plain" and "attachment" not in disposition:
                    body = mime_part.get_content()
                    break
                if content_type == "text/html" and not body and "attachment" not in disposition:
                    body = f"[HTML] {mime_part.get_content()}"
        else:
            mime_msg: MIMEPart = msg  # type: ignore[assignment]
            body = mime_msg.get_content()
        return body

