"""Application settings.

Every configurable value in the backend is read through this module — never `os.environ` inline,
never a hard-coded literal (S0 §12, `backend/CLAUDE.md`). Two rules shape what follows:

1. **No secret has a default.** A missing required value raises at construction, so the process
   fails to start rather than running with an insecure fallback (S0 §7.4, OWASP A05).
2. **Provider credentials are optional.** They are absent until the sandbox accounts are created;
   the app still starts, and each real adapter refuses to operate without its own keys. That keeps
   a missing Plaid key from blocking the ledger, while never silently substituting a fake.
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
    """Session signing key. 32 chars minimum — a short key is a weak signature, not a style nit."""

    database_url: SecretStr
    """Web API credential. Must map to a role WITHOUT BYPASSRLS (S0 §7.3)."""

    database_url_worker: SecretStr
    """Jobs and outbox worker. The BYPASSRLS role, deliberately a separate credential."""

    database_url_owner: SecretStr
    """Schema owner. Runs migrations only; never serves a request."""

    database_url_chat: SecretStr
    """`chat_readonly`'s own credential (ADR 19) — granted `SELECT` on the curated chat views only,
    a narrower and separately-provisioned role than `APP`'s. Required, no default, matching the
    other three role credentials above: a missing value must fail startup, never silently fall
    back to a broader-privileged connection for the LLM's tool calls."""

    redis_url: str
    """Sessions and rate-limit counters only. Never financial state (ADR 13)."""

    # --- Runtime posture ----------------------------------------------------------------------
    flask_env: Environment = "production"
    """Defaults to production so an unset value fails secure, not open."""

    flask_debug: bool = False

    # --- Field encryption (ADR 23) ------------------------------------------------------------
    azure_key_vault_url: str | None = None
    azure_keyvault_wrap_key_name: str | None = None
    local_cipher_key: SecretStr | None = None
    """Base64 32-byte key for LocalDevCipher. Ignored when a Key Vault wrap key is configured."""

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
    """Not a `SecretStr` -- a Stripe publishable key is explicitly meant to be embedded in
    client-side code (Stripe's own naming), unlike every other credential in this section. The
    frontend's Stripe.js `verifyIdentity(client_secret)` call needs it and has no other way to
    obtain it (`GET /api/v1/identity/config`)."""

    openai_api_key: SecretStr | None = None
    openai_org_id: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    """S11/ADR 18: a tunable setting, not an architectural decision — start cost-efficient, upgrade
    only if answer quality demands it (NFR-11's six-week budget)."""

    chat_daily_query_cap: int = 50
    """S11 §5.2/NFR-16 — per-customer, per-day cap on chat turns, independent of the per-turn tool
    iteration cap below. A conservative default, adjustable without a code change."""

    chat_max_tool_iterations: int = 6
    """S11 §5.2/NFR-16 — bounds a single turn's tool-calling loop, independent of the daily cap:
    caps one confused turn's cost and rules out an infinite tool-calling loop."""

    # --- Business tunables (S2/S3 — defensible engineering defaults, not compliance sign-offs;
    # flagged for review against actual NACHA/ACH limits before go-live, S2 §5.2) --------------
    kyc_max_attempts: int = 3
    """S2 §3.2: after this many rejected `kyc_session` attempts, `customer.kyc_status` locks to
    `rejected` and requires manual adviser override to reopen."""

    deposit_cap_per_transaction: Money = Money("25000.00")
    deposit_cap_per_day: Money = Money("50000.00")
    """S2 §5.2 step 2. Per-customer, per-transaction and daily-aggregate caps."""

    order_approval_threshold_usd: Money = Money("10000.00")
    """S3 §4: an order's notional strictly above this requires explicit customer approval
    (`draft -> awaiting_approval`) before it can be submitted; at or below, `draft -> approved`
    is immediate. `> threshold`, not `>=` — S3 §7 case 6 states the boundary explicitly."""

    drift_band_pct: Decimal = Decimal("0.05")
    """S9 §5: relative tolerance band, evaluated per holding against its own target weight (a
    20%-target holding triggers at 19%/21%, not a flat +/-5 percentage-point band). `> band`
    triggers; `== band` does not (S9 §9's documented boundary)."""

    rebalance_cash_buffer_pct: Decimal = Decimal("0.01")
    """S9 §5: fraction of portfolio value held back from every rebalance run's total buy sizing,
    absorbing price movement between the drift-check computation and the order's actual fill."""

    fee_rate_pct: Decimal
    """S10 §1/§10: the performance fee rate, a fraction (e.g. `0.02` for 2%), applied to TWR-derived
    gain above the high-water-mark. Required with **no default** -- a deliberate business decision
    the spec itself declines to invent (`docs/decisions/10-performance-fee-twr-high-water-mark.md`).
    Set to `0.0` for now (`DECISION-LOG.md`, 2026-09-05): a real, explicit rate that happens to be
    zero, not an absent one -- `DailyFeeAccrualJob` still runs and records true `gain_amount`
    figures even while `fee_amount` is zero."""

    dunning_max_attempts: int = 4
    """S10 §3.5: `DUNNING_MAX_ATTEMPTS`, a tunable setting -- after this many failed retries a
    `fee_charge` moves to `dunning`/`exhausted`, a standing customer-visible balance owed
    (FR-48)."""

    dunning_backoff_base_hours: int = 24
    """S10 §5: the base of `DunningService`'s exponential backoff (`base * 2**(attempt - 1)`
    hours) between retry attempts -- a defensible engineering default, flagged for business review
    before go-live, same posture as `KYC_MAX_ATTEMPTS`/the deposit caps."""

    @model_validator(mode="before")
    @classmethod
    def _blank_is_unset(cls, data: Any) -> Any:
        """Treat `KEY=` in a .env file as absent, not as an empty value.

        `.env.example` ships every optional credential blank, so without this an empty
        `AZURE_KEY_VAULT_URL` reads as "Key Vault is configured" and the app tries to reach a
        vault at "", and a blank `ALPACA_API_KEY_ID` reads as a real key. Dropping the key rather
        than mapping it to `None` is what makes all three cases correct at once: optionals fall
        back to `None`, fields with a default keep their default, and a required setting still
        fails as missing.
        """
        if not isinstance(data, dict):
            return data
        return {
            key: value
            for key, value in data.items()
            if not (isinstance(value, str) and not value.strip())
        }

    @model_validator(mode="after")
    def _debug_only_in_development(self) -> Settings:
        """OWASP A05. Debug mode leaks stack traces and enables the Werkzeug console."""
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
    """Process-wide settings. Cached so the .env file is read once, not per request."""
    # Values come from the environment and the .env file, not from call arguments.
    return Settings()
