"""`FeeChargeService` (S10 §5, ADR 10) — creates a billing period's pending charge (no I/O),
applies the Stripe outcome once the outbox has actually called the provider, and posts the
success-side ledger entry.

**Ledger construction for a successful charge, a judgment call this module documents rather than
guesses at silently.** ADR 10's prose ("debit fee_revenue_accrued / credit fee_revenue_collected,
and clear fees_accrued_payable") names three accounts, but a single zero-sum journal entry cannot
move all three by the same magnitude with only two legal signs (an odd count of equal-magnitude
legs can never sum to zero). This implementation clears `fees_accrued_payable` against
`fee_revenue_collected` -- the literal "clear the liability, recognize the cash now collected" pair
-- and leaves `fee_revenue_accrued` untouched at charge time, standing permanently as "gross fees
ever accrued to date" (mirroring how `fees_expense`/`dividend_income` already behave as lifetime
accumulators elsewhere in S1). `fee_revenue_collected` is the parallel "gross ever collected"
accumulator; the difference between the two, at any point, is what `fees_accrued_payable` should
show as still outstanding -- a cross-checkable invariant, not an enforced one. Flagged in the
fee-engineer close-out report as a deviation from the ADR's literal wording, not a silent guess.

**Locks to the as-published watermark, never a live figure (FR-47).** `_ensure_published` calls
`SnapshotService.publish` only if no snapshot already exists for this exact period -- mirroring S6
§7's own rule against a caller supplying an arbitrary timestamp -- so the same billing period is
never published twice with two different watermarks by two runs of this job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from app.core.money import Money
from app.models.fees.fee_charge import FeeCharge, FeeChargeStatus
from app.models.ledger.account import AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ops.inbound_event import InboundEventSource
from app.services.fees._shared import (
    get_or_create_customer_account,
    get_or_create_house_account,
    record_inbound_event,
)
from app.services.fees.dunning_service import DunningService
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.restatement.snapshot_service import SnapshotService

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import date

    from app.services.fees.uow import FeesUnitOfWork


class FeeChargeNotFoundError(RuntimeError):
    pass


class FeeChargeService:
    def __init__(
        self,
        uow: FeesUnitOfWork,
        *,
        dunning_max_attempts: int = 4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._dunning_max_attempts = dunning_max_attempts
        self._now = now

    # --- MonthlyFeeChargeJob's per-customer step (no provider I/O) -----------------------------

    def create_pending_charge(
        self, customer_id: uuid.UUID, *, period_start: date, period_end: date
    ) -> FeeCharge | None:
        """`None` when the period's `total_accrued` is zero -- a $0 Stripe charge is never
        created (`DECISION-LOG.md`'s general guard), whether that's because `FEE_RATE_PCT` is
        `0.0` or a customer genuinely had zero gain -- or when this period's charge already exists
        (idempotent re-run of the job).

        The read-then-insert below is a courtesy fast path, not the actual idempotency guarantee
        (F5 fix, S0 §10.1 audit): two concurrent or retried job runs could both pass the `existing
        is None` check before either commits. `uq_fee_charge_customer_period` is the real
        backstop -- the insert runs inside a `SAVEPOINT` so a unique-violation there rolls back
        only the attempted duplicate, then re-reads the row the other run just committed, matching
        `FeeAccrualService.accrue_for_customer`'s own established pattern for the identical race.
        """
        existing = self._uow.fee_charges.get_for_period(
            customer_id, period_start=period_start, period_end=period_end
        )
        if existing is not None:
            return existing

        accruals = self._uow.fee_accruals.list_for_period(
            customer_id, period_start=period_start, period_end=period_end
        )
        total = Money("0.00")
        for accrual in accruals:
            total += accrual.fee_amount
        if total == Money("0.00"):
            return None

        watermark = self._ensure_published(customer_id, period_start, period_end)

        charge = FeeCharge(
            customer_id=customer_id,
            billing_period_start=period_start,
            billing_period_end=period_end,
            total_accrued=total,
            as_published_watermark=watermark,
            status=FeeChargeStatus.PENDING,
        )
        try:
            with self._uow.session.begin_nested():
                self._uow.fee_charges.add(charge)
                self._uow.session.flush()
        except IntegrityError:
            return self._uow.fee_charges.get_for_period(
                customer_id, period_start=period_start, period_end=period_end
            )
        self._uow.outbox.enqueue("charge_fee", {"fee_charge_id": str(charge.id)})
        self._uow.notify_outbox_ready()
        return charge

    def _ensure_published(
        self, customer_id: uuid.UUID, period_start: date, period_end: date
    ) -> datetime:
        existing = self._uow.published_snapshots.latest_for_period(customer_id, period_start)
        if existing is not None and existing.period_end == period_end:
            return existing.publish_watermark
        snapshot = SnapshotService(self._uow).publish(customer_id, period_start, period_end)
        return snapshot.publish_watermark

    # --- Applying a provider outcome -- called from both the outbox handler and the webhook -----

    def apply_charge_success(self, fee_charge_id: uuid.UUID, *, stripe_charge_id: str) -> None:
        charge = self._uow.fee_charges.get_by_id(fee_charge_id)
        if charge is None:
            raise FeeChargeNotFoundError(f"no fee_charge {fee_charge_id}")
        if charge.status is FeeChargeStatus.SUCCEEDED:
            return  # idempotent: already applied by the outbox handler or an earlier webhook

        payable_account = get_or_create_customer_account(
            self._uow, customer_id=charge.customer_id, role=AccountRole.FEES_ACCRUED_PAYABLE
        )
        collected_account = get_or_create_house_account(
            self._uow, role=AccountRole.FEE_REVENUE_COLLECTED
        )
        event = record_inbound_event(
            self._uow,
            source=InboundEventSource.STRIPE,
            kind="fee_charge_succeeded",
            payload={
                "fee_charge_id": str(charge.id),
                "stripe_charge_id": stripe_charge_id,
                "amount": str(charge.total_accrued),
            },
        )
        entry = PostingService(self._uow).post(
            entry_type=JournalEntryType.FEE_ADJUSTMENT,
            effective_date=self._now().astimezone(UTC).date(),
            source_event_id=event.id,
            legs=[
                PostingLeg(account_id=payable_account.id, amount_money=-charge.total_accrued),
                PostingLeg(account_id=collected_account.id, amount_money=charge.total_accrued),
            ],
            memo="performance fee charge succeeded (S10 §5, ADR 10)",
        )
        charge.status = FeeChargeStatus.SUCCEEDED
        charge.stripe_charge_id = stripe_charge_id
        charge.journal_entry_id = entry.id

        dunning = self._uow.dunning_states.get_by_fee_charge_id(charge.id)
        if dunning is not None:
            self._uow.session.delete(dunning)

    def apply_charge_failure(self, fee_charge_id: uuid.UUID) -> None:
        charge = self._uow.fee_charges.get_by_id(fee_charge_id)
        if charge is None:
            raise FeeChargeNotFoundError(f"no fee_charge {fee_charge_id}")
        if charge.status in (FeeChargeStatus.SUCCEEDED, FeeChargeStatus.DUNNING):
            return  # idempotent: already resolved, or exhausted and no longer auto-retried

        dunning_service = DunningService(
            self._uow, max_attempts=self._dunning_max_attempts, now=self._now
        )
        existing = self._uow.dunning_states.get_by_fee_charge_id(charge.id)
        if existing is None:
            charge.status = FeeChargeStatus.FAILED
            dunning_service.start(charge)
        else:
            dunning_service.record_retry_failure(existing, charge)


__all__ = ["FeeChargeNotFoundError", "FeeChargeService"]
