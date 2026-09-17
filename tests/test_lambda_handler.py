import json
import logging
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError

from lambda_handler import (
    JSON_HEADERS,
    _create_repository,
    _parse_wait_timeout_seconds,
    _response,
    handler,
)
from services import ValidationCodeTimeoutError


def _event(wait_timeout_seconds: str | None = None):
    query = (
        None
        if wait_timeout_seconds is None
        else {"waitTimeoutSeconds": wait_timeout_seconds}
    )
    return {
        "requestContext": {
            "http": {"method": "GET", "path": "/api/v1/validation-code"}
        },
        "queryStringParameters": query,
    }


@pytest.fixture(autouse=True)
def clear_repository_cache():
    _create_repository.cache_clear()
    yield
    _create_repository.cache_clear()


def test_handler_accepts_direct_lambda_invocation():
    with patch("lambda_handler._create_repository"), patch("lambda_handler.ValidationCodeService") as service_class:
        service_class.return_value.get_validation_code = AsyncMock(return_value="123456")
        response = handler({"waitTimeoutSeconds": "15"}, None)
    assert response["statusCode"] == 200


def _body(response):
    return json.loads(response["body"])


def test_create_repository_authenticates_only_once():
    gmail_service = MagicMock()
    repository = MagicMock()
    with (
        patch("lambda_handler.GmailAuthenticator") as authenticator_class,
        patch("lambda_handler.GmailRepository", return_value=repository),
    ):
        authenticator_class.return_value.authenticate.return_value = gmail_service

        assert _create_repository() is repository
        assert _create_repository() is repository

    authenticator_class.return_value.authenticate.assert_called_once_with()


def test_response_uses_http_api_proxy_format():
    response = _response(200, {"message": "Código encontrado."})

    assert response == {
        "statusCode": 200,
        "headers": JSON_HEADERS,
        "body": '{"message": "Código encontrado."}',
        "isBase64Encoded": False,
    }


def test_parser_returns_none_when_parameter_is_omitted():
    assert _parse_wait_timeout_seconds(None) is None


@pytest.mark.parametrize("value", ["0", "15"])
def test_parser_accepts_timeout_boundaries(value):
    assert _parse_wait_timeout_seconds(value) == int(value)


@pytest.mark.parametrize("value", ["-1", "16", "invalid"])
def test_parser_rejects_timeout_outside_the_supported_range(value):
    with pytest.raises(ValueError, match="invalid wait timeout"):
        _parse_wait_timeout_seconds(value)


def test_handler_returns_400_for_timeout_above_limit():
    response = handler(_event("16"), None)

    assert response["statusCode"] == 400
    assert _body(response)["error"]["code"] == (
        "INVALID_WAIT_TIMEOUT_SECONDS"
    )


def test_handler_accepts_fifteen_seconds():
    with (
        patch("lambda_handler._create_repository"),
        patch("lambda_handler.ValidationCodeService") as service_class,
    ):
        service_class.return_value.get_validation_code = AsyncMock(
            return_value="123456"
        )
        response = handler(_event("15"), None)

    assert response["statusCode"] == 200
    assert service_class.call_args.args[1].wait_timeout_seconds == 15


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/validation-code"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
    ],
)
def test_handler_returns_404_for_unsupported_routes(method, path):
    event = _event()
    event["requestContext"]["http"] = {"method": method, "path": path}

    response = handler(event, None)

    assert response["statusCode"] == 404
    assert _body(response)["error"]["code"] == "NOT_FOUND"


def test_handler_uses_configured_timeout_when_parameter_is_omitted():
    with (
        patch("lambda_handler._create_repository"),
        patch("lambda_handler.Settings") as settings_class,
        patch("lambda_handler.ValidationCodeService") as service_class,
    ):
        settings_class.return_value.wait_timeout_seconds = 7
        service_class.return_value.get_validation_code = AsyncMock(
            return_value="123456"
        )

        response = handler(_event(), None)

    assert response["statusCode"] == 200
    assert service_class.call_args.args[1] is settings_class.return_value


def test_handler_returns_timeout_error():
    message = "Nenhuma nova mensagem foi recebida."
    with (
        patch("lambda_handler._create_repository"),
        patch("lambda_handler.ValidationCodeService") as service_class,
    ):
        service_class.return_value.get_validation_code = AsyncMock(
            side_effect=ValidationCodeTimeoutError(message)
        )

        response = handler(_event("0"), None)

    assert response["statusCode"] == 500
    assert _body(response) == {
        "error": {"code": "VALIDATION_CODE_TIMEOUT", "message": message}
    }


def test_handler_returns_authentication_error():
    with patch(
        "lambda_handler._create_repository",
        side_effect=RefreshError("token revoked"),
    ):
        response = handler(_event(), None)

    assert response["statusCode"] == 500
    assert _body(response)["error"] == {
        "code": "AUTHENTICATION_ERROR",
        "message": "Falha ao autenticar na Gmail API.",
    }


@pytest.mark.parametrize(
    "error",
    [ConnectionError("connection failed"), TimeoutError(), ssl.SSLError()],
)
def test_handler_returns_connection_error(error):
    with (
        patch("lambda_handler._create_repository"),
        patch("lambda_handler.ValidationCodeService") as service_class,
    ):
        service_class.return_value.get_validation_code = AsyncMock(side_effect=error)

        response = handler(_event(), None)

    assert response["statusCode"] == 500
    assert _body(response)["error"]["code"] == "GMAIL_API_CONNECTION_ERROR"


def test_handler_does_not_log_validation_code(caplog):
    code = "987654"
    caplog.set_level(logging.INFO)
    with (
        patch("lambda_handler._create_repository"),
        patch("lambda_handler.ValidationCodeService") as service_class,
    ):
        service_class.return_value.get_validation_code = AsyncMock(return_value=code)
        response = handler(_event("0"), None)

    assert response["statusCode"] == 200
    assert code not in caplog.text
