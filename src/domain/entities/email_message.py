from dataclasses import dataclass

@dataclass
class EmailMessage:
    """Entidade de domínio que representa uma mensagem de e-mail."""

    id: str
    sender: str
    recipient: str
    subject: str
    date: str
    body: str
    received_timestamp_ms: int = 0

    def contains_sender(self, email: str) -> bool:
        """Verifica se o remetente contém o endereço de e-mail informado."""
        return email.lower() in self.sender.lower()

    def contains_subject(self, keyword: str) -> bool:
        """Verifica se o assunto contém a palavra-chave informada."""
        return keyword.lower() in self.subject.lower()


