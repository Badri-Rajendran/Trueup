"""Flask application factory.

Wires the layers S0 §3 defines into one application. Everything below is cross-cutting setup;
no business logic lives here.

Wave 0 establishes the factory, security headers, the RFC 9457 error contract, correlation IDs,
and the cipher installation. Authentication, sessions and CSRF are wired in alongside the auth
surface, which owns their configuration.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, Response, g, request
from werkzeug.exceptions import HTTPException

from app.config import Settings, get_settings
from app.controllers.health import health_bp
from app.core.crypto import Cipher, set_cipher
from app.core.errors import AppError
from app.core.logging import (
    CORRELATION_HEADER,
    configure_logging,
    get_logger,
    new_correlation_id,
    set_correlation_id,
)
from app.extensions import init_engines, limiter, make_redis, talisman
from app.integrations.crypto.local_cipher import LocalDevCipher

log = get_logger(__name__)

# Content-Security-Policy for a JSON API: it serves no HTML and loads nothing, so everything is
# denied. The frontend is a separate origin with its own policy.
_CSP = {
    "default-src": "'none'",
    "frame-ancestors": "'none'",
    "base-uri": "'none'",
    "form-action": "'none'",
}


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    app = Flask(__name__)
    app.config["TRUEUP_SETTINGS"] = settings
    app.config["PROPAGATE_EXCEPTIONS"] = False
    # Rate-limit counters live in Redis so limits hold across every container replica; an
    # in-memory counter would give each replica its own budget (S0 §7.4, API4).
    app.config["RATELIMIT_STORAGE_URI"] = settings.redis_url
    app.config["RATELIMIT_HEADERS_ENABLED"] = True  # Retry-After on 429, per root CLAUDE.md

    configure_logging(
        json_output=settings.flask_env != "development",
        level=logging.DEBUG if settings.flask_debug else logging.INFO,
    )

    init_engines(settings)
    app.extensions["trueup_redis"] = make_redis(settings)
    set_cipher(_build_cipher(settings))

    talisman.init_app(
        app,
        force_https=settings.is_production,
        strict_transport_security=settings.is_production,
        content_security_policy=_CSP,
        frame_options="DENY",
        referrer_policy="no-referrer",
        session_cookie_secure=settings.is_production,
        session_cookie_http_only=True,
    )
    limiter.init_app(app)

    _register_request_hooks(app)
    _register_error_handlers(app)

    app.register_blueprint(health_bp)
    return app


def _build_cipher(settings: Settings) -> Cipher:
    """Select the Cipher adapter (ADR 23).

    Key Vault wherever it is configured. The local adapter is refused in production outright — a
    production deployment silently falling back to a config-supplied key is exactly the
    "insecure fallback" S0 §12 forbids.
    """
    if settings.has_key_vault_cipher:
        from app.integrations.azure.keyvault_cipher import KeyVaultCipher

        return KeyVaultCipher(
            vault_url=str(settings.azure_key_vault_url),
            key_name=str(settings.azure_keyvault_wrap_key_name),
        )

    if settings.is_production:
        raise RuntimeError(
            "AZURE_KEY_VAULT_URL and AZURE_KEYVAULT_WRAP_KEY_NAME are required in production; "
            "LocalDevCipher is not an acceptable production key store (ADR 23)."
        )
    if settings.local_cipher_key is None:
        raise RuntimeError(
            "Set LOCAL_CIPHER_KEY (base64 of 32 random bytes) for development, or configure "
            "Azure Key Vault. Encrypted columns must never fall back to plaintext."
        )
    return LocalDevCipher(settings.local_cipher_key.get_secret_value())


def _register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _assign_correlation_id() -> None:
        correlation_id = request.headers.get(CORRELATION_HEADER) or new_correlation_id()
        g.correlation_id = correlation_id
        set_correlation_id(correlation_id)

    @app.after_request
    def _echo_correlation_id(response: Response) -> Response:
        response.headers[CORRELATION_HEADER] = g.get("correlation_id", "")
        return response


def _register_error_handlers(app: Flask) -> None:
    """Every error leaves as RFC 9457 `application/problem+json` (S0 §8).

    The body carries a stable machine-readable `code` a frontend can branch on, and never a stack
    trace, SQL fragment, or internal identifier.
    """

    @app.errorhandler(AppError)
    def _app_error(exc: AppError) -> tuple[Any, int]:
        # The hierarchy already knows its own status, title and stable code; the only thing the
        # request layer adds is the correlation ID. `detail` stays server-side by construction.
        return _render(exc.to_problem(g.get("correlation_id", "")), exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException) -> tuple[Any, int]:
        return _problem(
            status=exc.code or 500,
            title=exc.name,
            code=exc.name.lower().replace(" ", "_"),
        )

    @app.errorhandler(Exception)
    def _unexpected_error(exc: Exception) -> tuple[Any, int]:
        # Logged in full server-side; the client is told nothing beyond the correlation ID, which
        # is what lets support join a customer's report to this exact trace.
        log.error("unhandled_exception", exc_info=exc)
        return _problem(status=500, title="Internal Server Error", code="internal_error")

    def _problem(*, status: int, title: str, code: str) -> tuple[Any, int]:
        return _render(
            {
                "type": "about:blank",
                "title": title,
                "status": status,
                "code": code,
                "correlation_id": g.get("correlation_id", ""),
            },
            status,
        )

    def _render(problem: dict[str, Any], status: int) -> tuple[Any, int]:
        from flask import jsonify

        response = jsonify(problem)
        response.mimetype = "application/problem+json"
        return response, status
