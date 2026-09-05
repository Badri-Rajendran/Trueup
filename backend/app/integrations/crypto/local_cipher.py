"""Local development and CI cipher (ADR 23).

Implements the same `Cipher` port and the same envelope layout as `KeyVaultCipher`, differing only
in where the key-encrypting key lives: a local base64 key here, an RSA key that never leaves Azure
Key Vault there. Because the contract suite runs against both, this adapter cannot silently drift
from the one that runs in production — the standard S0 §11 sets for every port.

This is not a fake. It performs real AES-256-GCM envelope encryption; it is simply keyed from
configuration rather than from a hardware-backed vault, which is why it is unsuitable for
production and gated on `flask_env` at startup.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.crypto import (
    DEK_BYTES,
    NONCE_BYTES,
    DecryptionError,
    pack_envelope,
    unpack_envelope,
)


class LocalDevCipher:
    """AES-256-GCM envelope encryption with a locally-configured key-encrypting key."""

    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.b64decode(key_b64, validate=True)
        except Exception as exc:  # any decode failure is the same user-facing error
            raise ValueError(
                "LOCAL_CIPHER_KEY must be valid base64 of 32 random bytes"
            ) from exc
        if len(key) != DEK_BYTES:
            raise ValueError(
                f"LOCAL_CIPHER_KEY must decode to exactly {DEK_BYTES} bytes, got {len(key)}"
            )
        self._kek = AESGCM(key)

    def encrypt(self, plaintext: str) -> bytes:
        # A fresh data key per value, so two customers holding the same token never produce the
        # same ciphertext, and so rotating the KEK only requires re-wrapping small keys.
        dek = os.urandom(DEK_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), None)

        wrap_nonce = os.urandom(NONCE_BYTES)
        wrapped_dek = wrap_nonce + self._kek.encrypt(wrap_nonce, dek, None)

        return pack_envelope(wrapped_dek, nonce, ciphertext)

    def decrypt(self, envelope: bytes) -> str:
        wrapped_dek, nonce, ciphertext = unpack_envelope(envelope)
        if len(wrapped_dek) <= NONCE_BYTES:
            raise DecryptionError("stored value is not a valid encryption envelope")

        wrap_nonce, wrapped = wrapped_dek[:NONCE_BYTES], wrapped_dek[NONCE_BYTES:]
        try:
            dek = self._kek.decrypt(wrap_nonce, wrapped, None)
            plaintext = AESGCM(dek).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            # Authentication failed: wrong key, tampered bytes, or a truncated value. The caller
            # is told only that the value is unreadable — see DecryptionError's docstring.
            raise DecryptionError("stored value could not be decrypted") from exc
        return plaintext.decode("utf-8")
