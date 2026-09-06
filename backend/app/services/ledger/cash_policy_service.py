"""`CashPolicyService` (S1 §5, ADR 5) — the two pure policy functions everything else in the
system reads instead of a stored "balance."

`holds(customer)`/`open_buy_commitments(customer)` are **owned by S3** (§5): this module defines
the contract as a `Protocol` and composes it, without implementing the holds table itself. Until
S3 wires a real implementation, callers supply whatever `HoldsProvider` they have -- there is no
default here, since a silent "always zero" implementation would produce a wrong `investable`/
`withdrawable` figure forever if a caller forgot to wire the real one (the same reasoning behind
`Watermark`'s required, no-default `as_of`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select

from app.core.money import Money
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation, SettlementObligationStatus

if TYPE_CHECKING:
    import uuid

    from app.models.ledger import LedgerUnitOfWork


class HoldsProvider(Protocol):
    """S3's contract (§5): order awaiting-approval and submitted-but-unfilled holds."""

    def holds(self, customer_id: uuid.UUID) -> Money: ...
    def open_buy_commitments(self, customer_id: uuid.UUID) -> Money: ...


class CashPolicyService:
    def __init__(self, uow: LedgerUnitOfWork, *, holds_provider: HoldsProvider) -> None:
        self._uow = uow
        self._holds_provider = holds_provider

    def settled_cash(self, customer_id: uuid.UUID) -> Money:
        """Cash postings whose journal entry needs no settlement confirmation, or whose
        obligation has confirmed (§5)."""
        no_obligation_needed = ~select(SettlementObligation.id).where(
            SettlementObligation.journal_entry_id == Posting.journal_entry_id
        ).exists()
        obligation_confirmed = select(SettlementObligation.id).where(
            SettlementObligation.journal_entry_id == Posting.journal_entry_id,
            SettlementObligation.status == SettlementObligationStatus.CONFIRMED,
        ).exists()

        statement = (
            select(func.coalesce(func.sum(Posting.amount_money), 0))
            .join(Account, Account.id == Posting.account_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.CASH,
                no_obligation_needed | obligation_confirmed,
            )
        )
        return self._as_money(self._uow.session.execute(statement).scalar_one())

    def unsettled_sale_proceeds(self, customer_id: uuid.UUID) -> Money:
        return self._unsettled_obligation_total(
            customer_id, entry_type=JournalEntryType.TRADE_SELL
        )

    def unsettled_deposit_proceeds(self, customer_id: uuid.UUID) -> Money:
        """Added alongside `unsettled_sale_proceeds` per S1 §5's amendment: a deposit is
        investable immediately, before its own obligation confirms, exactly as any other
        unsettled inflow."""
        return self._unsettled_obligation_total(customer_id, entry_type=JournalEntryType.DEPOSIT)

    def _unsettled_obligation_total(
        self, customer_id: uuid.UUID, *, entry_type: JournalEntryType
    ) -> Money:
        statement = (
            select(func.coalesce(func.sum(SettlementObligation.amount_money), 0))
            .join(JournalEntry, JournalEntry.id == SettlementObligation.journal_entry_id)
            .join(Account, Account.id == SettlementObligation.account_id)
            .where(
                Account.customer_id == customer_id,
                SettlementObligation.status == SettlementObligationStatus.PENDING,
                JournalEntry.entry_type == entry_type,
            )
        )
        return self._as_money(self._uow.session.execute(statement).scalar_one())

    @staticmethod
    def _as_money(value: Money | None) -> Money:
        """`COALESCE(..., 0)` guarantees SQL never returns `NULL`; mypy still sees the column's
        static type as nullable, so this narrows it in one place rather than at every call site."""
        return value if value is not None else Money("0.00")

    def withdrawable(self, customer_id: uuid.UUID) -> Money:
        """The brief's one hard constraint (FR-13): only confirmed, settled cash, minus holds."""
        return self.settled_cash(customer_id) - self._holds_provider.holds(customer_id)

    def investable(self, customer_id: uuid.UUID) -> Money:
        """Additionally counts unsettled inflows, deliberately **not** given to `withdrawable`
        (ADR 5's asymmetry, by design)."""
        return (
            self.settled_cash(customer_id)
            + self.unsettled_sale_proceeds(customer_id)
            + self.unsettled_deposit_proceeds(customer_id)
            - self._holds_provider.open_buy_commitments(customer_id)
            - self._holds_provider.holds(customer_id)
        )
