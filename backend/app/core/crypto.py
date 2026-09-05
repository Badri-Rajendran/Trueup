"""Field-level encryption at rest — the port and the persistence boundary (ADR 23).

Two columns hold secrets the application must be able to *recover*, so hashing is not an option:
`bank_link.plaid_access_token` (S2 §3.3) and the adviser TOTP secret (S0 §7.2).

This module owns the vocabulary; it does not own an implementation. `Cipher` is a `Protocol` and
`EncryptedText` is a SQLAlchemy `TypeDecorator`, so an encrypted column is declared `Mapped[str]`
and encryption happens at the persistence boundary — a caller cannot forget to encrypt, in the same
way ADR 16 made mixing money and units impossible rather than merely discouraged.

`app/core/` imports nothing else under `app/` (S0 §3): the adapters live in `app/integrations/`
and are injected at startup via `set_cipher`.

Envelope layout, identical for every adapter so the stored format never depends on which one is
configured:

    version (1) ‖ wrapped_dek_len (2, big-endian) ‖ wrapped_dek ‖ nonce (12) ‖ ciphertext
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

ENVELOPE_VERSION = 1
"""Bumped only by a change to the layout itself. Readers reject anything they do not know."""

NONCE_BYTES = 12
"""AES-GCM standard nonce length."""

DEK_BYTES = 32
"""AES-256 data-encryption key."""


class CryptoError(Exception):
    """Base class for every failure in this module."""


class DecryptionError(CryptoError):
    """Raised when a stored value cannot be authenticated and decrypted.

    Deliberately opaque: the message never distinguishes "wrong key" from "tampered ciphertext"
    from "truncated envelope", because that distinction is useful to an attacker probing stored
    values and useless to a legitimate caller, who can only ever act on "this value is unreadable".
    """


class CipherNotConfiguredError(CryptoError):
    """Raised when an encrypted column is used before an adapter was installed.

    The failure mode for a misconfigured cipher must be a crash, never a plaintext write.
    """


@runtime_checkable
class Cipher(Protocol):
    """Encrypts and decrypts a single field value.

    Implementations must produce the envelope layout documented above, and must raise
    `DecryptionError` — never return a wrong value — when authentication fails.
    """

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
    """Assemble the wire format. Shared by every adapter so the layout is defined exactly once."""
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
    """Split the wire format into (wrapped_dek, nonce, ciphertext).

    Every length is validated before it is used as an index, so a truncated or hostile value
    raises `DecryptionError` rather than producing a short read or an IndexError.
    """
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
    """A `str` column whose value is encrypted on write and decrypted on read.

    Declared on a model as `Mapped[str] = mapped_column(EncryptedText())`. The plaintext never
    reaches the database, and the ciphertext never reaches application code.

    Encrypted columns are opaque to SQL — they cannot be indexed, searched, or joined on. Neither
    value that uses this needs to be: a Plaid access token is reached *via* its `bank_link` row.
    """

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
