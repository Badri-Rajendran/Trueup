"""Flask application factory (S0 §3). Cross-cutting setup only, no business logic."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, Response, g, request
from werkzeug.exceptions import HTTPException

from app.config import Settings, get_settings
from app.controllers.admin.agent_requests import agent_requests_bp
from app.controllers.admin.customers import admin_customers_bp
from app.controllers.admin.kyc_overrides import admin_kyc_overrides_bp
from app.controllers.admin.rebalance import admin_rebalance_bp
from app.controllers.admin.staff_api_tokens import staff_api_tokens_bp
from app.controllers.api.auth import auth_bp, init_auth
from app.controllers.api.breaks import breaks_bp
from app.controllers.api.chat import chat_bp
from app.controllers.api.fees import fees_bp
from app.controllers.api.funding import funding_bp
from app.controllers.api.identity import identity_bp
from app.controllers.api.lots import lots_bp
from app.controllers.api.orders import orders_bp
from app.controllers.api.portfolios import portfolios_bp
from app.controllers.api.profile import profile_bp
from app.controllers.api.statements import statements_bp
from app.controllers.api.valuation import valuation_bp
from app.controllers.health import health_bp
from app.controllers.webhooks.plaid import plaid_webhooks_bp
from app.controllers.webhooks.stripe_billing import stripe_billing_bp
from app.controllers.webhooks.stripe_identity import stripe_identity_bp
from app.core.crypto import Cipher, set_cipher
from app.core.errors import AppError
from app.core.logging import (
    CORRELATION_HEADER,
    configure_logging,
    get_logger,
    new_correlation_id,
    set_correlation_id,
)
from app.core.security import set_audit_sink
from app.extensions import init_engines, limiter, make_redis, talisman
from app.integrations.crypto.local_cipher import LocalDevCipher
from app.jobs import register_cli
from app.services.ops.audit_sink import SqlAuditSink

log = get_logger(__name__)

# CSP for a JSON API: serves no HTML, everything denied.
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
    # Signs the session cookie and every CSRF token (S0 §7.1).
    app.config["SECRET_KEY"] = settings.secret_key.get_secret_value()
    app.config["PROPAGATE_EXCEPTIONS"] = False
    # Redis-backed so limits hold across replicas (S0 §7.4, API4).
    app.config["RATELIMIT_STORAGE_URI"] = settings.redis_url
    app.config["RATELIMIT_HEADERS_ENABLED"] = True  # Retry-After on 429

    configure_logging(
        json_output=settings.flask_env != "development",
        level=logging.DEBUG if settings.flask_debug else logging.INFO,
    )

    init_engines(settings)
    app.extensions["trueup_redis"] = make_redis(settings)
    set_cipher(_build_cipher(settings))
    set_audit_sink(SqlAuditSink())

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

    init_auth(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(valuation_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(identity_bp)
    app.register_blueprint(funding_bp)
    app.register_blueprint(breaks_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(portfolios_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(admin_rebalance_bp)
    app.register_blueprint(admin_customers_bp)
    app.register_blueprint(admin_kyc_overrides_bp)
    app.register_blueprint(agent_requests_bp)
    app.register_blueprint(staff_api_tokens_bp)
    app.register_blueprint(stripe_identity_bp)
    app.register_blueprint(plaid_webhooks_bp)
    app.register_blueprint(fees_bp)
    app.register_blueprint(stripe_billing_bp)
    register_cli(app)
    return app


def _build_cipher(settings: Settings) -> Cipher:
    """Select the Cipher adapter; local adapter refused in production (ADR 23)."""
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
    """Every error leaves as RFC 9457 `application/problem+json` (S0 §8)."""

    @app.errorhandler(AppError)
    def _app_error(exc: AppError) -> tuple[Any, int]:
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
        # Logged in full server-side; client gets only the correlation ID.
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
