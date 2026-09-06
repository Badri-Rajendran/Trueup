"""Azure Key Vault envelope encryption (ADR 23). RSA key-encrypting key never leaves the vault; a
fresh AES-256 data key per value is wrapped by Key Vault, so a stolen database dump yields only
ciphertext and wrapped keys. Unwrapped data keys are cached in-process behind a short TTL.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, KeyWrapAlgorithm

from app.core.crypto import (
    DEK_BYTES,
    NONCE_BYTES,
    DecryptionError,
    pack_envelope,
    unpack_envelope,
)

WRAP_ALGORITHM = KeyWrapAlgorithm.rsa_oaep_256

DEFAULT_CACHE_SIZE = 512
DEFAULT_CACHE_TTL_SECONDS = 300


class _DekCache:
    """Bounded, TTL'd map of wrapped data key to unwrapped data key."""

    def __init__(self, max_size: int, ttl_seconds: float) -> None:
        self._entries: OrderedDict[bytes, tuple[float, bytes]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, wrapped: bytes) -> bytes | None:
        entry = self._entries.get(wrapped)
        if entry is None:
            return None
        expires_at, dek = entry
        if time.monotonic() >= expires_at:
            del self._entries[wrapped]
            return None
        self._entries.move_to_end(wrapped)
        return dek

    def put(self, wrapped: bytes, dek: bytes) -> None:
        self._entries[wrapped] = (time.monotonic() + self._ttl, dek)
        self._entries.move_to_end(wrapped)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)


class KeyVaultCipher:
    """AES-256-GCM envelope encryption with the key-encrypting key held in Azure Key Vault."""

    def __init__(
        self,
        vault_url: str,
        key_name: str,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        credential = DefaultAzureCredential()
        key = KeyClient(vault_url=vault_url, credential=credential).get_key(key_name)
        self._crypto = CryptographyClient(key, credential=credential)
        self._cache = _DekCache(cache_size, cache_ttl_seconds)

    def encrypt(self, plaintext: str) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        dek = os.urandom(DEK_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), None)
        wrapped_dek = self._crypto.wrap_key(WRAP_ALGORITHM, dek).encrypted_key

        # Cache on write too: a value is very often read back moments after being stored.
        self._cache.put(wrapped_dek, dek)
        return pack_envelope(wrapped_dek, nonce, ciphertext)

    def decrypt(self, envelope: bytes) -> str:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        wrapped_dek, nonce, ciphertext = unpack_envelope(envelope)

        dek = self._cache.get(wrapped_dek)
        if dek is None:
            try:
                dek = self._crypto.unwrap_key(WRAP_ALGORITHM, wrapped_dek).key
            except AzureError as exc:
                # A vault outage is not a decryption failure: telling the caller "unreadable"
                # would invite treating a transient outage as permanent data loss.
                raise RuntimeError("Key Vault unwrap failed") from exc
            self._cache.put(wrapped_dek, dek)

        try:
            plaintext = AESGCM(dek).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise DecryptionError("stored value could not be decrypted") from exc
        return plaintext.decode("utf-8")
