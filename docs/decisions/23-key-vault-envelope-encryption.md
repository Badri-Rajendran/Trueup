# 23 — Azure Key Vault envelope encryption for field-level secrets at rest

## Status

Accepted

## Context

Two columns hold secrets that are neither hashable nor discardable, because the application must
recover the original value to function:

- `bank_link.plaid_access_token` (S2 §3.3) — "encrypted at rest, never logged, never returned in
  any API response." Every deposit and withdrawal needs the plaintext token to call Plaid.
- The adviser TOTP shared secret (S0 §7.2's mandatory MFA) — needed in plaintext to verify each
  login code.

Passwords use Argon2id (S0 §7.1) precisely because they never need recovering. These do, so hashing
is not an option and the question of *how* they are encrypted has a real answer that no spec or ADR
had given. S0 §12 says only that secrets come from Key Vault in deployed environments; it is silent
on encrypting individual database columns.

Root `CLAUDE.md` requires secrets encrypted at rest and kept out of logs and client payloads.

## Decision

**Field-level secrets are encrypted with envelope encryption, with the key-encrypting key held in
Azure Key Vault and never leaving it.**

Per value written:

1. Generate a fresh 256-bit data-encryption key (DEK).
2. AES-256-GCM encrypt the plaintext under that DEK, producing a nonce and an authenticated
   ciphertext — GCM so tampering with the stored bytes is detected on read, not silently decrypted
   into a wrong value.
3. Call Key Vault `wrapKey` on the DEK with an RSA key that never leaves the vault.
4. Store `wrapped_dek ‖ nonce ‖ ciphertext` as a single opaque `BYTEA` column.

Reading reverses it: `unwrapKey` recovers the DEK, then AES-GCM decrypts and authenticates.

Mechanism, so this is testable and not a discipline statement:

- `app/core/crypto.py` defines a `Cipher` `Protocol` and an `EncryptedText` SQLAlchemy
  `TypeDecorator`, so an encrypted column is declared `Mapped[str]` and encryption happens at the
  persistence boundary — a caller cannot forget to encrypt, exactly as ADR 16 made dimension-mixing
  impossible rather than merely discouraged. `core` stays dependency-free: it declares the
  `Protocol`, it does not import the adapter.
- `app/integrations/azure/keyvault_cipher.py` implements it against Key Vault.
- **Unwrapped DEKs are cached in-process behind an LRU with a short TTL.** Without this, every
  `bank_link` read makes a network round trip to Key Vault, putting deposit and withdrawal latency —
  and availability — directly behind another service. The cache holds only DEKs, never plaintext
  secrets, and never reaches disk or a log.
- `LocalDevCipher` implements the identical `Protocol` with a local AES-GCM key for development and
  CI, selected by configuration. The **contract suite runs against both**, so the local adapter
  cannot drift from the Key Vault one — the same standard S0 §11 applies to every other port.
- New settings: `AZURE_KEY_VAULT_URL` (already present) and `AZURE_KEYVAULT_WRAP_KEY_NAME`.
  Neither has a default; the application fails to start without them outside development (S0 §12).

## Consequences

- The database never holds a key capable of decrypting anything. A stolen database dump — backup,
  snapshot, or a compromised read replica — yields ciphertext and wrapped DEKs, and nothing else.
- Key rotation is a Key Vault operation on the wrap key plus a re-wrap pass over stored DEKs; the
  ciphertexts themselves never need rewriting, which is the main reason to envelope rather than
  encrypt directly under a Key Vault key.
- The application takes a runtime dependency on Key Vault availability for cold reads. The DEK cache
  bounds this to cache-miss reads rather than every read, and it is a deliberate trade for keeping
  the KEK out of application memory entirely.
- Encrypted columns are opaque to SQL: they cannot be indexed, searched, or joined on. Neither value
  needs that — a `plaid_access_token` is looked up *via* its `bank_link` row, never searched for.
- One more `Protocol` and two adapters, consistent with the existing ports-and-adapters layering
  (ADR 14) rather than a new pattern.

## Alternatives considered

- **App-layer Fernet with a `FIELD_ENCRYPTION_KEY` setting.** Simpler and with no runtime dependency
  on Key Vault, but the key itself would sit in application configuration and therefore in process
  memory, environment listings, and any config dump — the KEK's whole value is that it does not.
  Rejected by the user in favour of stronger key custody, with the latency cost accepted and bounded
  by the DEK cache above.
- **Postgres `pgcrypto`.** Rejected: the key travels inside SQL statements and session state, which
  puts it one `log_statement` setting or one slow-query log away from being written to disk in
  plaintext — an unacceptable failure mode for a regulated platform.
- **Calling Key Vault to encrypt each value directly, with no DEK.** Rejected: RSA cannot encrypt
  arbitrary-length data, it would put a Key Vault round trip on every single read with no cacheable
  intermediate, and rotating the key would require re-encrypting every stored value rather than
  re-wrapping small DEKs.
