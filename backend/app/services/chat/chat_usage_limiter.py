"""Per-customer daily chat query cap, checked before any model call (S11 §5.2 step 1, NFR-16)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from types import TracebackType


class _ChatMessageRepoProtocol(Protocol):
    def count_for_customer_since(self, customer_id: uuid.UUID, since: datetime) -> int: ...


class ChatUsageLimiterUnitOfWork(Protocol):
    """Satisfied by `ChatUnitOfWork`."""

    @property
    def chat_messages(self) -> _ChatMessageRepoProtocol: ...
    def __enter__(self) -> ChatUsageLimiterUnitOfWork: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class DailyQueryCapExceededError(Exception):
    """Raised by `check()` when the customer has already spent today's query cap (S11 §5.3)."""


class ChatUsageLimiter:
    def __init__(
        self, uow_factory: Callable[[], ChatUsageLimiterUnitOfWork], *, daily_query_cap: int
    ) -> None:
        self._uow_factory = uow_factory
        self._daily_query_cap = daily_query_cap

    def check(self, customer_id: uuid.UUID, *, now: datetime | None = None) -> None:
        """Raises `DailyQueryCapExceededError` if the cap was hit in the trailing 24 hours."""
        since = (now or datetime.now(UTC)) - timedelta(hours=24)
        with self._uow_factory() as uow:
            count = uow.chat_messages.count_for_customer_since(customer_id, since)
        if count >= self._daily_query_cap:
            raise DailyQueryCapExceededError(
                f"daily chat query cap ({self._daily_query_cap}) reached for this customer"
            )


__all__ = ["ChatUsageLimiter", "DailyQueryCapExceededError"]
