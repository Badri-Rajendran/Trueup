"""Settings must fail loudly rather than let the app start insecurely (S0 §12, A05)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

# Every required setting, with a valid throwaway value. Individual tests remove one at a time.
COMPLETE: dict[str, str] = {
    "SECRET_KEY": "x" * 32,
    "DATABASE_URL": "postgresql+psycopg://trueup_app:pw@localhost:5433/trueup",
    "DATABASE_URL_WORKER": "postgresql+psycopg://trueup_worker:pw@localhost:5433/trueup",
    "DATABASE_URL_OWNER": "postgresql+psycopg://trueup_owner:pw@localhost:5433/trueup",
    "DATABASE_URL_CHAT": "postgresql+psycopg://trueup_chat_readonly:pw@localhost:5433/trueup",
    "REDIS_URL": "redis://localhost:6380/0",
    "FEE_RATE_PCT": "0.0",
}


def build(**overrides: str | None) -> Settings:
    """Builds Settings from an explicit environment, clearing any of `COMPLETE`'s keys that
    `conftest.py`'s autouse fixture already sets in the process environment."""
    env = {**COMPLETE, **overrides}
    values = {k: v for k, v in env.items() if v is not None}
    with pytest.MonkeyPatch.context() as mp:
        for key in COMPLETE:
            mp.delenv(key, raising=False)
        return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_complete_environment_builds_settings() -> None:
    settings = build()
    assert settings.secret_key.get_secret_value() == "x" * 32
    assert settings.redis_url == "redis://localhost:6380/0"


@pytest.mark.parametrize("missing", sorted(COMPLETE))
def test_every_required_setting_is_required(missing: str) -> None:
    """Removing any one required setting must raise, never silently default."""
    with pytest.raises(ValidationError) as exc:
        build(**{missing: None})
    assert missing.lower() in str(exc.value).lower()


def test_secret_key_below_minimum_length_is_rejected() -> None:
    """A short SECRET_KEY is a weak session-signing key, not a style preference (A02/A07)."""
    with pytest.raises(ValidationError):
        build(SECRET_KEY="tooshort")


def test_environment_defaults_to_production() -> None:
    """Fail-secure: an unset FLASK_ENV must not mean 'development'."""
    assert build().flask_env == "production"


def test_debug_cannot_be_enabled_outside_development() -> None:
    """S0 §7.4 (A05): DEBUG=False is enforced outside dev, not left to deployment discipline."""
    with pytest.raises(ValidationError, match="debug"):
        build(FLASK_ENV="production", FLASK_DEBUG="true")


def test_debug_is_allowed_in_development() -> None:
    assert build(FLASK_ENV="development", FLASK_DEBUG="true").flask_debug is True


def test_provider_credentials_are_optional_until_supplied() -> None:
    """Adapters refuse to operate without keys; the app itself still starts."""
    settings = build()
    assert settings.alpaca_api_key_id is None
    assert settings.stripe_secret_key is None
    assert settings.has_alpaca_credentials is False


def test_provider_credentials_are_detected_when_present() -> None:
    settings = build(ALPACA_API_KEY_ID="PK123", ALPACA_API_SECRET_KEY="sk123")
    assert settings.has_alpaca_credentials is True


class TestBlankValuesAreTreatedAsUnset:
    """`.env.example` ships optional credentials as `KEY=`; an empty string must not read as set."""

    def test_blank_optional_credential_is_none(self) -> None:
        settings = build(ALPACA_API_KEY_ID="", ALPACA_API_SECRET_KEY="   ")
        assert settings.alpaca_api_key_id is None
        assert settings.has_alpaca_credentials is False

    def test_blank_key_vault_settings_do_not_look_configured(self) -> None:
        settings = build(AZURE_KEY_VAULT_URL="", AZURE_KEYVAULT_WRAP_KEY_NAME="")
        assert settings.has_key_vault_cipher is False

    def test_blank_value_falls_back_to_a_declared_default(self) -> None:
        assert build(ALPACA_BASE_URL="").alpaca_base_url == "https://paper-api.alpaca.markets"

    def test_blank_required_setting_still_fails(self) -> None:
        """Blank means "unset", which for a required setting is an error, not a default."""
        with pytest.raises(ValidationError):
            build(SECRET_KEY="")


def test_secrets_are_not_exposed_by_repr() -> None:
    """Secrets never reach a log; a settings dump is a log waiting to happen."""
    rendered = repr(build())
    assert "x" * 32 not in rendered
    assert "pw@localhost" not in rendered


def test_sqlalchemy_url_is_returned_as_plain_string() -> None:
    """The SecretStr wrapper must not leak into the DSN SQLAlchemy needs raw."""
    assert build().sqlalchemy_url.startswith("postgresql+psycopg://trueup_app:")
