"""`BreakAgingService` (S7 §7) — aging is a pure function of `opened_at`, computed on read, never
stored and therefore never able to go stale."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from app.models.reconciliation.reconciliation_break import ReconciliationBreak


class BreakAgingService:
    @staticmethod
    def age(break_row: ReconciliationBreak, *, now: datetime) -> timedelta:
        return now - break_row.opened_at


__all__ = ["BreakAgingService"]
