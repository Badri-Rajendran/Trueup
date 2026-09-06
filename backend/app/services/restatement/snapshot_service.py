"""`SnapshotService` (S6 §6, ADR 6) — `publish()` snapshots S4's live TWR/balance figures at a
fixed ledger watermark; `cross_check()` is ADR 6's tamper-detection invariant made runnable:
re-deriving a published period at its own `publish_watermark` must reproduce the stored snapshot
exactly, forever.

**`derive()` re-links from `sub_period_return`'s own bitemporal `recorded_at` dimension, rather
than a watermark-aware rewrite of `ValuationService`/`TwrService`.** Both of those (S4)
intentionally compute only the live, as-corrected present -- pinning them to an arbitrary past
`recorded_at` would mean threading a watermark through every ledger/price query they make, a
change to S4's own files well beyond this spec's scope. `sub_period_return.py`'s own module
docstring anticipates exactly this approach ("S6 pins to the watermark live at publication"): the
`[v_begin, v_end]` boundary dates a period decomposes into are driven only by external cash-flow
dates (S4 §5's `_boundaries`), and a deposit/withdrawal is not one of S6 §4's restatement triggers,
so those
boundaries are stable for any watermark at or after the point they were first computed. `derive()`
therefore reuses `TwrService.boundaries()` to find the windows, then reads each window's own
*stored* `sub_period_return` row as of the requested watermark and relinks with `TwrService.link()`
-- re-linking from existing numbers, never re-deriving from raw postings (S6 §5).

**`balance` is a period's last sub-period's `value_end`, not a separate valuation query.**
`TwrService._sub_period_return` already sets `value_end` to `ValuationService.value_book(...,
v_end).total_value` -- for the final window in a period, `v_end == period_end`, so that row's
`value_end` *is* the whole-book valuation at period close. Reusing it means `cross_check` needs no
watermark-aware `ValuationService` at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select, text

from app.core.money import Money, Units
from app.core.watermark import Watermark
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.services.valuation.twr_service import TwrService

if TYPE_CHECKING:
    import uuid
    from datetime import date
    from decimal import Decimal

    from app.models.marketdata.sub_period_return import SubPeriodReturn
    from app.services.restatement.restatement_service import RestatementCapableUnitOfWork


class SnapshotCrossCheckFailedError(RuntimeError):
    """ADR 6's tamper-detection alarm: re-deriving a published period at its own `publish_watermark`
    no longer reproduces the stored snapshot. This means history was rewritten somewhere the
    append-only guarantees were supposed to prevent (NFR-1) -- never caught and logged quietly
    (S6 §9 edge case 4); the caller (`RestatementService`, the periodic sweep job) must let this
    propagate as a loud operational failure."""


class SnapshotDerivationError(RuntimeError):
    """No `sub_period_return` row exists yet for one of a period's sub-period windows as of the
    requested watermark -- `derive()` cannot answer for a period `TwrService.compute_twr` had not
    yet fully computed by that point in time. Should never happen for a genuinely published
    snapshot (`publish()` only runs after `compute_twr` has populated every window)."""


@dataclass(frozen=True, slots=True)
class DerivedFigures:
    twr: Decimal
    balance: Money
    sub_periods: tuple[SubPeriodReturn, ...]


class SnapshotService:
    def __init__(self, uow: RestatementCapableUnitOfWork) -> None:
        self._uow = uow
        self._twr_service: TwrService = TwrService(uow)  # type: ignore[arg-type]

    def publish(
        self, customer_id: uuid.UUID, period_start: date, period_end: date
    ) -> PublishedSnapshot:
        """S6 §6: snapshot the live figures, pinned to the database's own transaction-start `now()`
        (never the application clock) -- Postgres's `now()` is constant for the whole transaction,
        so it is guaranteed to be `>=` the `recorded_at` of every `sub_period_return` row
        `compute_twr` just wrote in this same transaction, however close application-clock skew
        might otherwise cut it."""
        result = self._twr_service.compute_twr(customer_id, period_start, period_end)
        watermark_dt = self._uow.session.execute(text("SELECT now()")).scalar_one()
        balance = result.sub_periods[-1].value_end if result.sub_periods else Money("0.00")

        snapshot = PublishedSnapshot(
            customer_id=customer_id,
            period_start=period_start,
            period_end=period_end,
            publish_watermark=watermark_dt,
            twr=result.twr,
            balance=balance,
            holdings_json=self._current_holdings(customer_id, period_end),
            published_at=watermark_dt,
        )
        self._uow.published_snapshots.add(snapshot)
        self._uow.session.flush()
        return snapshot

    def derive(
        self, customer_id: uuid.UUID, period_start: date, period_end: date, watermark: Watermark
    ) -> DerivedFigures:
        """ADR 6's `derive(customer_id, period, recorded_at <= watermark)` -- see module docstring
        for why this reads `sub_period_return` rows rather than re-deriving from the ledger."""
        boundaries = self._twr_service.boundaries(customer_id, period_start, period_end)
        sub_periods: list[SubPeriodReturn] = []
        for v_begin, v_end in pairwise(boundaries):
            row = self._uow.sub_period_returns.as_of_for_sub_period(
                customer_id=customer_id,
                sub_period_start=v_begin,
                sub_period_end=v_end,
                as_of=watermark,
            )
            if row is None:
                raise SnapshotDerivationError(
                    f"no sub_period_return for customer {customer_id} window [{v_begin}, {v_end}] "
                    f"as of {watermark}"
                )
            sub_periods.append(row)

        twr = TwrService.link(sub_periods)
        balance = sub_periods[-1].value_end if sub_periods else Money("0.00")
        return DerivedFigures(twr=twr, balance=balance, sub_periods=tuple(sub_periods))

    def cross_check(self, snapshot: PublishedSnapshot) -> None:
        """S6 §6's runnable form of ADR 6's invariant. Must hold forever -- a failure here is
        NFR-1's own tamper detector firing, not a business-logic bug (S6 §9 edge case 4)."""
        watermark = Watermark.as_published(snapshot.publish_watermark)
        derived = self.derive(
            snapshot.customer_id, snapshot.period_start, snapshot.period_end, watermark
        )
        if derived.twr != snapshot.twr or derived.balance != snapshot.balance:
            raise SnapshotCrossCheckFailedError(
                f"published_snapshot {snapshot.id} (customer {snapshot.customer_id}, period "
                f"[{snapshot.period_start}, {snapshot.period_end}]) no longer reproduces at its "
                f"own publish_watermark {snapshot.publish_watermark}: "
                f"twr {snapshot.twr} vs derived {derived.twr}, "
                f"balance {snapshot.balance} vs derived {derived.balance}"
            )

    def _current_holdings(self, customer_id: uuid.UUID, as_of_date: date) -> dict[str, Any]:
        """A point-in-time holdings snapshot, live, "sufficient to reconstruct what was shown"
        (S6 §3.1) -- the same per-security query shape `ValuationService._position_units` uses
        internally (S4), duplicated rather than reused because that method is private and returns
        only a total, not the per-security breakdown a statement needs to show."""
        statement = (
            select(Account.security_id, func.coalesce(func.sum(Posting.quantity_units), 0))
            .join(Posting, Posting.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.POSITION_UNITS,
                JournalEntry.effective_date <= as_of_date,
            )
            .group_by(Account.security_id)
        )
        rows = self._uow.session.execute(statement).all()

        holdings: dict[str, Any] = {}
        for security_id, units in rows:
            if security_id is None or units == Units("0"):
                continue
            security = self._uow.securities.get_by_id(security_id)
            close = self._uow.daily_closes.latest_confirmed(
                security_id=security_id, market_date=as_of_date
            )
            holdings[str(security_id)] = {
                "symbol": security.symbol if security is not None else None,
                "quantity": str(units),
                "close_price": str(close.close_price) if close is not None else None,
            }
        return holdings


__all__ = [
    "DerivedFigures",
    "SnapshotCrossCheckFailedError",
    "SnapshotDerivationError",
    "SnapshotService",
]
