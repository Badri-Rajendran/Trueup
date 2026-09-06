"""Field-level encryption at rest — the port and the persistence boundary (ADR 23).

Envelope layout: version(1) | wrapped_dek_len(2, big-endian) | wrapped_dek | nonce(12) | ciphertext.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

ENVELOPE_VERSION = 1
"""Bumped only by a change to the layout itself."""

NONCE_BYTES = 12
"""AES-GCM standard nonce length."""

DEK_BYTES = 32
"""AES-256 data-encryption key."""


class CryptoError(Exception):
    """Base class for every failure in this module."""


class DecryptionError(CryptoError):
    """Raised when a stored value cannot be authenticated and decrypted. Deliberately opaque."""


class CipherNotConfiguredError(CryptoError):
    """Raised when an encrypted column is used before an adapter was installed."""


@runtime_checkable
class Cipher(Protocol):
    """Encrypts/decrypts a field value. Must raise `DecryptionError`, never return a wrong value."""

    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, envelope: bytes) -> str: ...


_cipher: Cipher | None = None


def set_cipher(cipher: Cipher) -> None:
    """Install the process-wide cipher. Called once during application startup."""
    global _cipher
    _cipher = cipher


def reset_cipher() -> None:
    """Clear the installed cipher. Used by tests; never called in production code."""
    global _cipher
    _cipher = None


def get_cipher() -> Cipher:
    if _cipher is None:
        raise CipherNotConfiguredError(
            "No Cipher installed. Call set_cipher() during application startup before any "
            "encrypted column is read or written."
        )
    return _cipher


def pack_envelope(wrapped_dek: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Assemble the wire format. Shared by every adapter."""
    if len(nonce) != NONCE_BYTES:
        raise CryptoError(f"nonce must be {NONCE_BYTES} bytes, got {len(nonce)}")
    return (
        bytes([ENVELOPE_VERSION])
        + len(wrapped_dek).to_bytes(2, "big")
        + wrapped_dek
        + nonce
        + ciphertext
    )


def unpack_envelope(envelope: bytes) -> tuple[bytes, bytes, bytes]:
    """Split the wire format into (wrapped_dek, nonce, ciphertext); rejects a truncated value."""
    header = 1 + 2
    if len(envelope) < header:
        raise DecryptionError("stored value is not a valid encryption envelope")
    if envelope[0] != ENVELOPE_VERSION:
        raise DecryptionError(f"unsupported encryption envelope version: {envelope[0]}")

    wrapped_len = int.from_bytes(envelope[1:3], "big")
    nonce_start = header + wrapped_len
    ciphertext_start = nonce_start + NONCE_BYTES
    if len(envelope) < ciphertext_start:
        raise DecryptionError("stored value is not a valid encryption envelope")

    return (
        envelope[header:nonce_start],
        envelope[nonce_start:ciphertext_start],
        envelope[ciphertext_start:],
    )


class EncryptedText(TypeDecorator[str]):
    """A `str` column whose value is encrypted on write and decrypted on read. Opaque to SQL."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        return get_cipher().encrypt(value)

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return get_cipher().decrypt(bytes(value))
