"""Daily fee-accrual posting `DailyFeeAccrualJob` calls once per customer (S10 §4, ADR 10).

Actual/365 day-count; accrual + HWM update run inside a `SAVEPOINT` so a duplicate-date
run for one customer rolls back cleanly without discarding the rest of the job (S10 §8 edge case 4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from app.models.fees.fee_accrual import FeeAccrual
from app.models.ledger.account import AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ops.inbound_event import InboundEventSource
from app.services.fees._shared import (
    get_or_create_customer_account,
    get_or_create_house_account,
    record_inbound_event,
)
from app.services.fees.high_water_mark_service import HighWaterMarkService
from app.services.ledger.posting_service import PostingLeg, PostingService

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import date

    from app.core.money import Money
    from app.services.fees.uow import FeesUnitOfWork

_DAYS_PER_YEAR = Decimal(365)


class FeeAccrualService:
    def __init__(
        self,
        uow: FeesUnitOfWork,
        *,
        fee_rate_pct: Decimal,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._fee_rate_pct = fee_rate_pct
        self._hwm_service = HighWaterMarkService(uow, now=now)
        self._now = now

    def accrue_for_customer(
        self, customer_id: uuid.UUID, accrual_date: date
    ) -> FeeAccrual | None:
        """`None` means no funded basis yet, or this date was already accrued (S10 §8 edge case 4)."""
        shadow_value = self._hwm_service.shadow_nav(customer_id, accrual_date)
        if shadow_value is None:
            return None

        try:
            with self._uow.session.begin_nested():
                hwm = self._hwm_service.get_or_create(customer_id, shadow_value=shadow_value)
                gain = self._hwm_service.ratchet(hwm, shadow_value=shadow_value)
                daily_rate = self._fee_rate_pct / _DAYS_PER_YEAR
                fee_amount = gain * daily_rate
                accrual = self._post_accrual(
                    customer_id, accrual_date, gain_amount=gain, fee_amount=fee_amount
                )
        except IntegrityError:
            return None
        return accrual

    def _post_accrual(
        self,
        customer_id: uuid.UUID,
        accrual_date: date,
        *,
        gain_amount: Money,
        fee_amount: Money,
    ) -> FeeAccrual:
        payable_account = get_or_create_customer_account(
            self._uow, customer_id=customer_id, role=AccountRole.FEES_ACCRUED_PAYABLE
        )
        revenue_account = get_or_create_house_account(
            self._uow, role=AccountRole.FEE_REVENUE_ACCRUED
        )
        # Internally-derived posting, no webhook -- source MARKETDATA (cf. CorporateActionService).
        event = record_inbound_event(
            self._uow,
            source=InboundEventSource.MARKETDATA,
            kind="fee_accrual",
            payload={
                "customer_id": str(customer_id),
                "accrual_date": accrual_date.isoformat(),
                "gain_amount": str(gain_amount),
                "fee_amount": str(fee_amount),
            },
        )
        entry = PostingService(self._uow).post(
            entry_type=JournalEntryType.FEE_ADJUSTMENT,
            effective_date=accrual_date,
            source_event_id=event.id,
            legs=[
                PostingLeg(account_id=payable_account.id, amount_money=fee_amount),
                PostingLeg(account_id=revenue_account.id, amount_money=-fee_amount),
            ],
            memo="performance fee daily accrual (S10 §4, ADR 10)",
        )
        accrual = FeeAccrual(
            customer_id=customer_id,
            accrual_date=accrual_date,
            gain_amount=gain_amount,
            fee_amount=fee_amount,
            journal_entry_id=entry.id,
        )
        self._uow.fee_accruals.add_for_date(accrual)
        self._uow.session.flush()
        return accrual


__all__ = ["FeeAccrualService"]
