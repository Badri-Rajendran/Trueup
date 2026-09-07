"""`FundingSummaryService` (S2 §5.2/§6, FR-6) — assembles the funding page's cash read model.

Mirrors `app/services/fees/fee_summary_service.py`'s shape: a small frozen dataclass plus a thin
assembly service built from a UoW and its collaborators. Unlike fees, the two deposit caps are
deploy-time settings the controller already reads from `get_settings()` -- this service takes them
as constructor arguments rather than reading config itself (services in this codebase never call
`get_settings()` directly).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.money import Money
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.posting import Posting
from app.services.identity._shared import deposited_on

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from app.services.identity.funding_uow import FundingUnitOfWork
    from app.services.ledger.cash_policy_service import CashPolicyService


@dataclass(frozen=True, slots=True)
class FundingCashSummary:
    withdrawable: Money
    investable: Money
    outstanding_receivable: Money
    deposit_cap_per_transaction: Money
    deposit_cap_per_day: Money
    deposited_today: Money


class FundingSummaryService:
    def __init__(
        self,
        uow: FundingUnitOfWork,
        *,
        cash_policy: CashPolicyService,
        deposit_cap_per_transaction: Money,
        deposit_cap_per_day: Money,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._cash_policy = cash_policy
        self._deposit_cap_per_transaction = deposit_cap_per_transaction
        self._deposit_cap_per_day = deposit_cap_per_day
        self._now = now

    def summarize(self, customer_id: uuid.UUID) -> FundingCashSummary:
        withdrawable = self._cash_policy.withdrawable(customer_id)
        investable = self._cash_policy.investable(customer_id)
        deposited_today = deposited_on(
            self._uow, customer_id, effective_date=self._now().date()
        )
        outstanding_receivable = self._outstanding_receivable(customer_id)
        return FundingCashSummary(
            withdrawable=withdrawable,
            investable=investable,
            outstanding_receivable=outstanding_receivable,
            deposit_cap_per_transaction=self._deposit_cap_per_transaction,
            deposit_cap_per_day=self._deposit_cap_per_day,
            deposited_today=deposited_today,
        )

    def _outstanding_receivable(self, customer_id: uuid.UUID) -> Money:
        """`0.00` for the common case: a customer whose deposits have never bounced has no
        `customer_receivable` account row at all."""
        statement = (
            select(func.coalesce(func.sum(Posting.amount_money), 0))
            .join(Account, Account.id == Posting.account_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.CUSTOMER_RECEIVABLE,
            )
        )
        total = self._uow.session.execute(statement).scalar_one()
        return Money(total) if total is not None else Money("0.00")


__all__ = ["FundingCashSummary", "FundingSummaryService"]
