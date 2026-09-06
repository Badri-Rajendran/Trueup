"""Reacts to a correcting entry, recomputes affected `sub_period_return` rows, and cross-checks
published periods (S6 §4-5). Takes a `Protocol`, not a concrete UoW, so trigger sites can recompute
within their own already-open transaction.
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
    """Structural dependency `RestatementService`/`SnapshotService` need."""

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
    """S10 §6's fee-disclosure hook, an optional constructor dependency."""

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
        """S6 §5's pipeline: recomputes windows containing `affected_date`, logs an audit event
        per window, then re-links and cross-checks affected published periods (S6 §6)."""
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
