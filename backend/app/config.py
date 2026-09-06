"""Application settings, read only through this module (S0 §12).

No secret has a default; provider credentials are optional until sandbox accounts exist.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.money import Money

Environment = Literal["development", "testing", "production"]


class Settings(BaseSettings):
    """Typed, validated configuration for the whole backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core (required; no defaults) ---------------------------------------------------------
    secret_key: SecretStr = Field(min_length=32)
    """Session signing key, 32 chars minimum."""

    database_url: SecretStr
    """Web API DB credential (non-BYPASSRLS role, S0 §7.3)."""

    database_url_worker: SecretStr
    """Jobs/outbox worker DB credential (BYPASSRLS role)."""

    database_url_owner: SecretStr
    """Schema-owner credential; migrations only, never serves a request."""

    database_url_chat: SecretStr
    """`chat_readonly` credential, scoped to curated chat views (ADR 19)."""

    redis_url: str
    """Sessions and rate-limit counters only, never financial state (ADR 13)."""

    # --- Runtime posture ----------------------------------------------------------------------
    flask_env: Environment = "production"
    """Defaults to production so an unset value fails secure."""

    flask_debug: bool = False

    # --- Field encryption (ADR 23) ------------------------------------------------------------
    azure_key_vault_url: str | None = None
    azure_keyvault_wrap_key_name: str | None = None
    local_cipher_key: SecretStr | None = None
    """Base64 32-byte LocalDevCipher key; ignored when Key Vault is configured."""

    # --- Provider credentials (optional until the sandbox accounts exist) ---------------------
    alpaca_api_key_id: SecretStr | None = None
    alpaca_api_secret_key: SecretStr | None = None
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    plaid_client_id: SecretStr | None = None
    plaid_secret: SecretStr | None = None
    plaid_env: str = "sandbox"

    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret_identity: SecretStr | None = None
    stripe_webhook_secret_billing: SecretStr | None = None
    stripe_publishable_key: str | None = None
    """Stripe publishable key; safe for client-side embedding, unlike other creds here."""

    openai_api_key: SecretStr | None = None
    openai_org_id: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    """Chat completion model id (S11/ADR 18)."""

    chat_daily_query_cap: int = 50
    """Per-customer daily chat turn cap (S11 §5.2/NFR-16)."""

    chat_max_tool_iterations: int = 6
    """Per-turn tool-call iteration cap (S11 §5.2/NFR-16)."""

    # --- Business tunables (S2/S3 — review before go-live, S2 §5.2) ---------------------------
    kyc_max_attempts: int = 3
    """Rejected KYC attempts before `customer.kyc_status` locks to `rejected` (S2 §3.2)."""

    deposit_cap_per_transaction: Money = Money("25000.00")
    deposit_cap_per_day: Money = Money("50000.00")
    """Per-customer transaction and daily deposit caps (S2 §5.2 step 2)."""

    order_approval_threshold_usd: Money = Money("10000.00")
    """Order notional strictly above this requires customer approval (S3 §4, S3 §7 case 6)."""

    drift_band_pct: Decimal = Decimal("0.05")
    """Relative drift tolerance per holding before rebalance triggers (S9 §5, §9)."""

    rebalance_cash_buffer_pct: Decimal = Decimal("0.01")
    """Cash fraction withheld from rebalance buy sizing (S9 §5)."""

    fee_rate_pct: Decimal
    """Performance fee rate on TWR gain above high-water-mark; no default by design
    (S10 §1/§10, DECISION-LOG.md 2026-09-05)."""

    dunning_max_attempts: int = 4
    """Failed retries before a `fee_charge` moves to `dunning`/`exhausted` (S10 §3.5, FR-48)."""

    dunning_backoff_base_hours: int = 24
    """Base hours for `DunningService`'s exponential backoff (S10 §5)."""

    outbox_max_attempts: int = 5
    """Retries before an outbox row moves to `dead_letter` (S0 §9)."""

    mcp_server_host: str = "0.0.0.0"  # noqa: S104 -- container's only network interface.
    mcp_server_port: int = 8001
    """MCP server bind port, separate from Flask's 8000 (S13/ADR 24)."""

    @model_validator(mode="before")
    @classmethod
    def _blank_is_unset(cls, data: Any) -> Any:
        """Treat `KEY=` in a .env file as absent, not as an empty value."""
        if not isinstance(data, dict):
            return data
        return {
            key: value
            for key, value in data.items()
            if not (isinstance(value, str) and not value.strip())
        }

    @model_validator(mode="after")
    def _debug_only_in_development(self) -> Settings:
        """OWASP A05: debug mode is permitted only in development."""
        if self.flask_debug and self.flask_env != "development":
            raise ValueError(
                f"flask_debug cannot be enabled when flask_env is {self.flask_env!r}; "
                "debug mode is permitted only in development"
            )
        return self

    # --- Derived accessors --------------------------------------------------------------------

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def sqlalchemy_url_worker(self) -> str:
        return self.database_url_worker.get_secret_value()

    @property
    def sqlalchemy_url_owner(self) -> str:
        return self.database_url_owner.get_secret_value()

    @property
    def sqlalchemy_url_chat(self) -> str:
        return self.database_url_chat.get_secret_value()

    @property
    def is_production(self) -> bool:
        return self.flask_env == "production"

    @property
    def has_alpaca_credentials(self) -> bool:
        return self.alpaca_api_key_id is not None and self.alpaca_api_secret_key is not None

    @property
    def has_plaid_credentials(self) -> bool:
        return self.plaid_client_id is not None and self.plaid_secret is not None

    @property
    def has_stripe_credentials(self) -> bool:
        return self.stripe_secret_key is not None

    @property
    def has_openai_credentials(self) -> bool:
        return self.openai_api_key is not None

    @property
    def has_key_vault_cipher(self) -> bool:
        return (
            self.azure_key_vault_url is not None
            and self.azure_keyvault_wrap_key_name is not None
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, cached so .env is read once."""
    return Settings()
