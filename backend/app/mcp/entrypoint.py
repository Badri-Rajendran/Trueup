"""MCP server's `main()`, run as a separate ASGI process from the WSGI Flask app (S13 §4.1, ADR 24).

Duplicates `app/__init__.py`'s engine/cipher wiring rather than importing it, to avoid pulling
in every controller blueprint for a process that registers none.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings, get_settings
from app.core.crypto import Cipher, set_cipher
from app.core.logging import configure_logging, get_logger
from app.extensions import init_engines
from app.integrations.crypto.local_cipher import LocalDevCipher
from app.mcp import build_server

log = get_logger(__name__)


def _build_cipher(settings: Settings) -> Cipher:
    """Mirrors `app/__init__.py::_build_cipher`; duplicated, not imported."""
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


def main() -> None:
    settings = get_settings()
    configure_logging(
        json_output=settings.flask_env != "development",
        level=logging.DEBUG if settings.flask_debug else logging.INFO,
    )
    init_engines(settings)
    set_cipher(_build_cipher(settings))

    log.info(
        "mcp_server_starting", host=settings.mcp_server_host, port=settings.mcp_server_port
    )
    server = build_server()
    asyncio.run(
        server.run_streamable_http_async(
            host=settings.mcp_server_host, port=settings.mcp_server_port
        )
    )


if __name__ == "__main__":
    main()
