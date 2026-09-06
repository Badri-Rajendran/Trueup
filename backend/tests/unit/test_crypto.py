"""Field-level encryption at rest: the envelope layout every Cipher adapter must share (ADR 23)."""

from __future__ import annotations

import base64
import os

import pytest

from app.core.crypto import (
    ENVELOPE_VERSION,
    CipherNotConfiguredError,
    DecryptionError,
    EncryptedText,
    get_cipher,
    reset_cipher,
    set_cipher,
)
from app.integrations.crypto.local_cipher import LocalDevCipher


def make_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def cipher() -> LocalDevCipher:
    return LocalDevCipher(make_key())


def test_round_trip(cipher: LocalDevCipher) -> None:
    assert cipher.decrypt(cipher.encrypt("access-sandbox-abc123")) == "access-sandbox-abc123"


def test_round_trip_unicode(cipher: LocalDevCipher) -> None:
    assert cipher.decrypt(cipher.encrypt("naïve—✓ 秘密")) == "naïve—✓ 秘密"


def test_round_trip_empty_string(cipher: LocalDevCipher) -> None:
    assert cipher.decrypt(cipher.encrypt("")) == ""


def test_same_plaintext_encrypts_differently_each_time(cipher: LocalDevCipher) -> None:
    """Fresh data key and nonce per value: identical tokens must not produce identical rows."""
    assert cipher.encrypt("same") != cipher.encrypt("same")


def test_ciphertext_is_versioned(cipher: LocalDevCipher) -> None:
    """A version byte is what makes a future key-rotation or algorithm change readable."""
    assert cipher.encrypt("v")[0] == ENVELOPE_VERSION


def test_unknown_envelope_version_is_rejected(cipher: LocalDevCipher) -> None:
    envelope = bytearray(cipher.encrypt("v"))
    envelope[0] = 0xFE
    with pytest.raises(DecryptionError, match="version"):
        cipher.decrypt(bytes(envelope))


def test_tampered_ciphertext_is_detected(cipher: LocalDevCipher) -> None:
    """AES-GCM is authenticated: a flipped bit must raise, never decrypt to a wrong value."""
    envelope = bytearray(cipher.encrypt("balance-critical-token"))
    envelope[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(envelope))


def test_tampered_wrapped_key_is_detected(cipher: LocalDevCipher) -> None:
    envelope = bytearray(cipher.encrypt("balance-critical-token"))
    envelope[8] ^= 0x01  # inside the wrapped data key
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(envelope))


def test_truncated_envelope_is_detected(cipher: LocalDevCipher) -> None:
    with pytest.raises(DecryptionError):
        cipher.decrypt(cipher.encrypt("token")[:10])


def test_another_key_cannot_decrypt(cipher: LocalDevCipher) -> None:
    other = LocalDevCipher(make_key())
    with pytest.raises(DecryptionError):
        other.decrypt(cipher.encrypt("token"))


def test_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32"):
        LocalDevCipher(base64.b64encode(os.urandom(16)).decode())


def test_plaintext_never_appears_in_the_envelope(cipher: LocalDevCipher) -> None:
    assert b"access-sandbox" not in cipher.encrypt("access-sandbox-abc123")


class TestEncryptedTextColumn:
    """The TypeDecorator is what makes forgetting to encrypt impossible (ADR 23, cf. ADR 16)."""

    def test_bind_and_result_round_trip(self, cipher: LocalDevCipher) -> None:
        set_cipher(cipher)
        try:
            column = EncryptedText()
            stored = column.process_bind_param("secret-token", None)  # type: ignore[arg-type]
            assert isinstance(stored, bytes)
            assert b"secret-token" not in stored
            assert column.process_result_value(stored, None) == "secret-token"  # type: ignore[arg-type]
        finally:
            reset_cipher()

    def test_none_passes_through(self, cipher: LocalDevCipher) -> None:
        set_cipher(cipher)
        try:
            column = EncryptedText()
            assert column.process_bind_param(None, None) is None  # type: ignore[arg-type]
            assert column.process_result_value(None, None) is None  # type: ignore[arg-type]
        finally:
            reset_cipher()

    def test_unconfigured_cipher_raises_rather_than_storing_plaintext(self) -> None:
        """A misconfigured cipher must crash, never write plaintext."""
        reset_cipher()
        with pytest.raises(CipherNotConfiguredError):
            get_cipher()
        with pytest.raises(CipherNotConfiguredError):
            EncryptedText().process_bind_param("secret", None)  # type: ignore[arg-type]
