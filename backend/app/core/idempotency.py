"""Idempotency vocabulary and store inversion, with no persistence-layer imports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import uuid
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    customer_id: uuid.UUID
    key: str
    request_hash: str
    response_status: int
    response_body: dict[str, Any]
    created_at: datetime


class IdempotencyStore(Protocol):
    """Persistence port implemented by the operations repository in the model layer."""

    def find(self, *, customer_id: uuid.UUID, key: str) -> IdempotencyRecord | None: ...

    def save(self, record: IdempotencyRecord) -> None: ...


class IdempotencyStoreResolver(Protocol):
    def __call__(self) -> IdempotencyStore: ...


class IdempotencyStoreNotConfiguredError(RuntimeError):
    """Raised rather than silently falling back to an in-memory financial-state store."""


class IdempotencyConflictError(RuntimeError):
    """A client reused an idempotency key with a different request body."""


_resolver: IdempotencyStoreResolver | None = None


def set_idempotency_store_resolver(resolver: IdempotencyStoreResolver) -> None:
    """Install persistence wiring at application-factory startup."""
    global _resolver
    _resolver = resolver


def reset_idempotency_store_resolver() -> None:
    """Clear startup wiring for test isolation."""
    global _resolver
    _resolver = None


def resolve_idempotency_store() -> IdempotencyStore:
    if _resolver is None:
        raise IdempotencyStoreNotConfiguredError(
            "No idempotency store resolver installed. Register the PostgreSQL-backed store during "
            "application startup."
        )
    return _resolver()


def request_hash(body: bytes) -> str:
    """Hash the exact request bytes so semantically changed replays cannot slip through."""
    return hashlib.sha256(body).hexdigest()


def resolve_replay(record: IdempotencyRecord, body: bytes) -> tuple[int, dict[str, Any]]:
    """Return the stored response or reject a key reused with a changed body."""
    if record.request_hash != request_hash(body):
        raise IdempotencyConflictError("idempotency key was reused with a different request body")
    return record.response_status, record.response_body
