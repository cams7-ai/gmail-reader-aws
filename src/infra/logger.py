"""Configuração centralizada de logging para toda a aplicação."""
import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """
    Configura o sistema de logging global com formato padronizado.

    Args:
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Retorna um logger configurado para o módulo informado.

    Args:
        name: Nome do módulo (normalmente __name__).

    Returns:
        Logger configurado.
    """
    return logging.getLogger(name)


