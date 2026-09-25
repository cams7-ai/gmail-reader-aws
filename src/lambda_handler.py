import asyncio
import json
import ssl
from dataclasses import replace
from functools import lru_cache
from typing import Any

from google.auth.exceptions import RefreshError

from config import Settings
from infra import GmailAuthenticator
from repositories import GmailRepository
from services import ValidationCodeService, ValidationCodeTimeoutError

MAX_WAIT_TIMEOUT_SECONDS = 15
JSON_HEADERS = {"content-type": "application/json; charset=utf-8"}


@lru_cache(maxsize=1)
def _create_repository() -> GmailRepository:
    settings = Settings()
    gmail_service = GmailAuthenticator(settings).authenticate()
    return GmailRepository(gmail_service)


def _response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": JSON_HEADERS,
        "body": json.dumps(payload, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def _parse_wait_timeout_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        timeout = int(value)
    except ValueError as exc:
        raise ValueError("invalid wait timeout") from exc
    if not 0 <= timeout <= MAX_WAIT_TIMEOUT_SECONDS:
        raise ValueError("invalid wait timeout")
    return timeout


def _get_validation_code(settings: Settings) -> str:
    try:
        return asyncio.run(ValidationCodeService(_create_repository(), settings).get_validation_code())
    except RefreshError:
        # A warm execution environment may still hold credentials from a rotated secret.
        _create_repository.cache_clear()
        return asyncio.run(ValidationCodeService(_create_repository(), settings).get_validation_code())


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    direct_invocation = "requestContext" not in event
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    if not direct_invocation and (
        http.get("method") != "GET"
        or http.get("path") != "/api/v1/validation-code"
    ):
        return _response(
            404,
            {"error": {"code": "NOT_FOUND", "message": "Rota não encontrada."}},
        )
    query = event if direct_invocation else (event.get("queryStringParameters") or {})
    try:
        timeout = _parse_wait_timeout_seconds(query.get("waitTimeoutSeconds"))
    except ValueError:
        return _response(
            400,
            {
                "error": {
                    "code": "INVALID_WAIT_TIMEOUT_SECONDS",
                    "message": "waitTimeoutSeconds deve ser um inteiro entre 0 e 15.",
                }
            },
        )

    settings = Settings()
    if timeout is not None:
        settings = replace(settings, wait_timeout_seconds=timeout)

    try:
        code = _get_validation_code(settings)
    except ValidationCodeTimeoutError as exc:
        return _response(
            500,
            {"error": {"code": "VALIDATION_CODE_TIMEOUT", "message": str(exc)}},
        )
    except RefreshError:
        return _response(
            500,
            {
                "error": {
                    "code": "AUTHENTICATION_ERROR",
                    "message": "Falha ao autenticar na Gmail API.",
                }
            },
        )
    except (ConnectionError, TimeoutError, ssl.SSLError):
        return _response(
            500,
            {
                "error": {
                    "code": "GMAIL_API_CONNECTION_ERROR",
                    "message": "Falha temporária ao conectar à Gmail API.",
                }
            },
        )

    return _response(
        200,
        {"code": code, "message": "Código de validação encontrado com sucesso."},
    )
