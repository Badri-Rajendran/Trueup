"""Per-customer daily chat query cap, checked before any model call (S11 §5.2 step 1, NFR-16).

`check()` takes an already-open unit of work rather than opening its own -- a security-review
finding (chat audit, 2026-09-07): the previous version ran its `SELECT count(...)` in its own,
separate transaction that committed and closed *before* `begin_turn()`'s own transaction inserted
the new message rows. Under READ COMMITTED (Postgres's default), two concurrent requests could
each read a count just under the cap and both proceed -- no reordering of the count-then-insert
sequence closes that race on its own; it needs the two to share a transaction that a lock
serializes. See `ChatOrchestrationService.begin_turn()`, which now acquires a
`pg_advisory_xact_lock` keyed on the customer before calling this."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid


class _ChatMessageRepoProtocol(Protocol):
    def count_for_customer_since(self, customer_id: uuid.UUID, since: datetime) -> int: ...


class ChatUsageLimiterUnitOfWork(Protocol):
    """Satisfied by `ChatUnitOfWork`. No `__enter__`/`__exit__` here -- the caller owns the
    transaction (and the advisory lock inside it); this type only reads through it."""

    @property
    def chat_messages(self) -> _ChatMessageRepoProtocol: ...


class DailyQueryCapExceededError(Exception):
    """Raised by `check()` when the customer has already spent today's query cap (S11 §5.3)."""


class ChatUsageLimiter:
    def __init__(self, *, daily_query_cap: int) -> None:
        self._daily_query_cap = daily_query_cap

    def check(
        self,
        uow: ChatUsageLimiterUnitOfWork,
        customer_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> None:
        """Raises `DailyQueryCapExceededError` if the cap was hit in the trailing 24 hours. Must
        run inside a transaction that already holds this customer's advisory lock -- otherwise
        this reintroduces the exact race the caller-owned-transaction signature exists to close."""
        since = (now or datetime.now(UTC)) - timedelta(hours=24)
        count = uow.chat_messages.count_for_customer_since(customer_id, since)
        if count >= self._daily_query_cap:
            raise DailyQueryCapExceededError(
                f"daily chat query cap ({self._daily_query_cap}) reached for this customer"
            )


__all__ = ["ChatUsageLimiter", "DailyQueryCapExceededError"]
