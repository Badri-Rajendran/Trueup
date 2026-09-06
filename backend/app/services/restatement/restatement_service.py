"""`RestatementService` (S6 §4-5) — reacts to a correcting entry S1/S4/S5 already posted and
recomputes exactly the `sub_period_return` row(s) it touches, then re-links and cross-checks every
already-published period the correction reaches. Adds no second listening mechanism (S6 §4):
callers pass the same `effective_date`/`source_event_id` the correcting entry itself already
carries, right after posting it.

**No producer exists yet for `manual_correction`/`corrected_close`.** `PostingService.correct()`
(S1) has zero callers today, and no code path writes a superseding `confirmed` `daily_close` row
either (`app/jobs/daily_valuation.py`'s `DailyValuationJob` only ever writes one confirmed row per
`market_date`) -- this service is ready to be called with either trigger the moment a producer
lands (S7's custodian simulator is expected to be the first, per its own spec §9), same honest-
disclosure posture S5 used for its own open items (`corporate_action_service.py`).

**Why `RestatementService.__init__` takes a `Protocol`, not a concrete `UnitOfWork` class.** The
real trigger sites (`WashSaleService`, `CorporateActionService`) run under `LotsUnitOfWork`/
`OrdersUnitOfWork`, not this package's own `RestatementUnitOfWork` -- and must, since recomputing a
`sub_period_return` row has to see the correcting entry's own not-yet-committed postings in the
*same* transaction (a freshly opened `UnitOfWork` would read a stale, pre-correction ledger). This
`Protocol` (S0 §5's "services depend on their aggregate's own Protocol" pattern) is what both
`RestatementUnitOfWork` and `LotsUnitOfWork` (via
`app.models.restatement.RestatementModelsUnitOfWork`, composed by both) satisfy structurally, with
no shared base class needed between them.

**S10's own hook (§6, FR-47), added as an optional constructor dependency rather than a new
`RestatementCapableUnitOfWork` member.** Extending that `Protocol` with `fee_charges`/
`fee_restatement_disclosures` would force every existing structural implementer -- `LotsUnitOfWork`
included, a file this sub-project does not own -- to gain those accessors too, just to keep
satisfying the `Protocol`. `fee_disclosure_checker: FeeDisclosureChecker | None = None` avoids that:
every existing call site (`WashSaleService`, `CorporateActionService`) keeps constructing
`RestatementService(self._uow)` exactly as before, unaffected. Wiring a real checker into those two
production trigger sites (`fee_disclosure_checker=FeeRestatementDisclosureService(uow)`, one extra
constructor argument each) is flagged in the fee-engineer close-out report as owed integration work
outside this sub-project's own file boundary, not silently left undone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.models.restatement.restatement_event import RestatementEvent
from app.services.restatement.snapshot_service import SnapshotService
from app.services.valuation.twr_service import TwrService

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from sqlalchemy.orm import Session

    from app.models.marketdata.daily_close import DailyCloseRepository
    from app.models.marketdata.security import SecurityRepository
    from app.models.marketdata.sub_period_return import SubPeriodReturn, SubPeriodReturnRepository
    from app.models.restatement.published_snapshot import PublishedSnapshotRepository
    from app.models.restatement.restatement_event import (
        RestatementEventRepository,
        RestatementTriggerType,
    )


class RestatementCapableUnitOfWork(Protocol):
    """The structural dependency `RestatementService`/`SnapshotService` need -- see module
    docstring. `securities`/`daily_closes` are needed only for `SnapshotService._current_holdings`,
    included here rather than in a second Protocol to keep one structural contract for the whole
    `app/services/restatement/` package."""

    @property
    def session(self) -> Session: ...
    @property
    def securities(self) -> SecurityRepository: ...
    @property
    def daily_closes(self) -> DailyCloseRepository: ...
    @property
    def sub_period_returns(self) -> SubPeriodReturnRepository: ...
    @property
    def published_snapshots(self) -> PublishedSnapshotRepository: ...
    @property
    def restatement_events(self) -> RestatementEventRepository: ...


class FeeDisclosureChecker(Protocol):
    """S10 §6's hook -- see module docstring for why this is an optional constructor dependency
    rather than a `RestatementCapableUnitOfWork` member. The real implementation
    (`app.services.fees.fee_restatement_disclosure_service.FeeRestatementDisclosureService`) checks
    for a `succeeded` `fee_charge` on `[period_start, period_end]` and inserts a
    `fee_restatement_disclosure` row if one is found; a no-op checker (or `None`) is exactly as
    correct for a customer S10 has no fee history for."""

    def check_and_disclose(
        self,
        *,
        customer_id: uuid.UUID,
        period_start: date,
        period_end: date,
        restatement_event_id: uuid.UUID,
    ) -> None: ...


class RestatementService:
    def __init__(
        self,
        uow: RestatementCapableUnitOfWork,
        *,
        fee_disclosure_checker: FeeDisclosureChecker | None = None,
    ) -> None:
        self._uow = uow
        self._twr_service: TwrService = TwrService(uow)  # type: ignore[arg-type]
        self._fee_disclosure_checker = fee_disclosure_checker

    def restate(
        self,
        *,
        customer_id: uuid.UUID,
        affected_date: date,
        trigger_type: RestatementTriggerType,
        source_event_id: uuid.UUID,
    ) -> tuple[SubPeriodReturn, ...]:
        """S6 §5's pipeline. Recomputes every stored `sub_period_return` window containing
        `affected_date` (usually exactly one), logs a `restatement_event` per window recomputed,
        then re-links and `cross_check`s every already-published period any of those windows falls
        within (S6 §6). A window that has never been published is still recomputed and logged
        (S6 §9 edge case 2) -- there is simply nothing to cross-check for it yet.

        `affected_date` with no stored window containing it (S4 has never computed a TWR touching
        this date) still logs one audit row, using `affected_date` itself as a degenerate
        single-day period -- there is no wider window to recompute, since nothing was ever stored
        for one, but the audit trail's own purpose (S6 §3.2: "why did my return change") still
        applies to "we checked, and there was nothing to restate."
        """
        windows = self._uow.sub_period_returns.containing(
            customer_id=customer_id, on_date=affected_date
        )

        if not windows:
            self._uow.restatement_events.add(
                RestatementEvent(
                    customer_id=customer_id,
                    affected_period_start=affected_date,
                    affected_period_end=affected_date,
                    trigger_type=trigger_type,
                    trigger_source_event_id=source_event_id,
                )
            )
            return ()

        recomputed: list[SubPeriodReturn] = []
        events: list[RestatementEvent] = []
        for window in windows:
            event = RestatementEvent(
                customer_id=customer_id,
                affected_period_start=window.sub_period_start,
                affected_period_end=window.sub_period_end,
                trigger_type=trigger_type,
                trigger_source_event_id=source_event_id,
            )
            self._uow.restatement_events.add(event)
            events.append(event)
            recomputed.append(
                self._twr_service.recompute_sub_period(
                    customer_id, window.sub_period_start, window.sub_period_end
                )
            )
        # Assigns each event's id (a Python-side `default=uuid.uuid4`, populated at flush) -- S10's
        # hook below needs a real `restatement_event_id` to link a disclosure to.
        self._uow.session.flush()

        self._relink_and_cross_check(customer_id, affected_date, restatement_event_id=events[0].id)
        return tuple(recomputed)

    def _relink_and_cross_check(
        self, customer_id: uuid.UUID, affected_date: date, *, restatement_event_id: uuid.UUID
    ) -> None:
        snapshot_service = SnapshotService(self._uow)
        touched = self._uow.published_snapshots.list_touching(customer_id, affected_date)

        relinked_periods: set[tuple[date, date]] = set()
        for snapshot in touched:
            period_key = (snapshot.period_start, snapshot.period_end)
            if period_key not in relinked_periods:
                # S6 §5 step 3/4: re-link the live figure now, rather than waiting for the next
                # ad-hoc read to trigger it -- `compute_twr` is idempotent (S4's own reuse-or-
                # recompute design), so relinking a period more than once here is harmless.
                self._twr_service.compute_twr(
                    customer_id, snapshot.period_start, snapshot.period_end
                )
                relinked_periods.add(period_key)
            # S6 §6: must still hold at the OLD watermark -- a loud failure (never a caught,
            # logged exception), per S6 §9 edge case 4.
            snapshot_service.cross_check(snapshot)

            # S10 §6: a restatement landing on a period that already has a `succeeded` fee_charge
            # never reopens that charge -- it only flags the account for disclosure (FR-47).
            if self._fee_disclosure_checker is not None:
                self._fee_disclosure_checker.check_and_disclose(
                    customer_id=customer_id,
                    period_start=snapshot.period_start,
                    period_end=snapshot.period_end,
                    restatement_event_id=restatement_event_id,
                )


__all__ = ["RestatementCapableUnitOfWork", "RestatementService"]
