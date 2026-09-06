"""`CorporateActionService` (S5 §6) — the dividend two-step and the units-only split entry.

Holdings are read from `tax_lot` state directly, never a parallel holdings tally (S5 §1's own
framing, "derive realized/unrealized gains from lot state alone") -- so `declare_dividend_ex_date`
and `apply_split` both start from `TaxLotRepository.list_customers_holding`, applying the action to
every customer currently holding the security rather than requiring a caller to already know who
they are.

**No caller exists yet for any of this class's three methods (S5's own open item,
DECISION-LOG.md).** Each still calls `RestatementService.restate()` after every entry it posts
(S6 §4: `dividend`/`split` are two of S6's named trigger `entry_type`s), so restatement fires
correctly the moment a real caller (a pay-date job, an operator action) lands -- not something to
wire only once that caller exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.money import Units
from app.models.ledger.account import AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ops.inbound_event import InboundEventSource
from app.models.restatement.restatement_event import RestatementTriggerType
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.lots._shared import (
    get_or_create_customer_account,
    get_or_create_house_account,
    record_inbound_event,
    require_customer_account,
)
from app.services.restatement.restatement_service import RestatementService

if TYPE_CHECKING:
    import uuid
    from datetime import date
    from decimal import Decimal

    from app.core.money import Money, Price
    from app.services.lots.uow import LotsUnitOfWork


class CorporateActionService:
    def __init__(self, uow: LotsUnitOfWork) -> None:
        self._uow = uow
        self._posting_service = PostingService(uow)

    def declare_dividend_ex_date(
        self, *, security_id: uuid.UUID, per_share_amount: Price, ex_date: date
    ) -> list[JournalEntry]:
        """S5 §6.1's ex-date step: entitlement recognized, cash not yet moved. One entry per
        customer currently holding `security_id` (`dividend_income` is a single house account
        per `account.py`'s own convention; `dividend_receivable` is per-customer)."""
        entries: list[JournalEntry] = []
        income_account = get_or_create_house_account(self._uow, role=AccountRole.DIVIDEND_INCOME)

        for customer_id in self._uow.tax_lots.list_customers_holding(security_id):
            quantity_held = self._uow.tax_lots.total_remaining(customer_id, security_id)
            if quantity_held <= Units("0"):
                continue
            amount = per_share_amount * quantity_held

            receivable_account = get_or_create_customer_account(
                self._uow, customer_id=customer_id, role=AccountRole.DIVIDEND_RECEIVABLE
            )
            event = record_inbound_event(
                self._uow,
                source=InboundEventSource.MARKETDATA,
                kind="dividend_ex_date",
                payload={
                    "customer_id": str(customer_id),
                    "security_id": str(security_id),
                    "quantity_held": str(quantity_held),
                    "per_share_amount": str(per_share_amount),
                },
            )
            entry = self._posting_service.post(
                entry_type=JournalEntryType.DIVIDEND,
                effective_date=ex_date,
                source_event_id=event.id,
                legs=[
                    PostingLeg(account_id=receivable_account.id, amount_money=amount),
                    PostingLeg(account_id=income_account.id, amount_money=-amount),
                ],
                memo=f"dividend entitlement, ex-date {ex_date} (S5 §6.1)",
            )
            entries.append(entry)

            RestatementService(self._uow).restate(
                customer_id=customer_id,
                affected_date=ex_date,
                trigger_type=RestatementTriggerType.LATE_DIVIDEND,
                source_event_id=entry.source_event_id,
            )
        return entries

    def pay_dividend(
        self, *, customer_id: uuid.UUID, amount: Money, pay_date: date
    ) -> JournalEntry:
        """S5 §6.1's pay-date step: cash finally arrives, days later. `amount` is the same figure
        `declare_dividend_ex_date` posted to that customer's receivable -- the caller (a future
        pay-date job, S5 §9's open parameter on how corporate actions are triggered) is
        responsible for reading it back off that entry/receivable balance."""
        cash_account = require_customer_account(
            self._uow, customer_id=customer_id, role=AccountRole.CASH
        )
        receivable_account = get_or_create_customer_account(
            self._uow, customer_id=customer_id, role=AccountRole.DIVIDEND_RECEIVABLE
        )

        event = record_inbound_event(
            self._uow,
            source=InboundEventSource.MARKETDATA,
            kind="dividend_pay_date",
            payload={"customer_id": str(customer_id), "amount": str(amount)},
        )
        entry = self._posting_service.post(
            entry_type=JournalEntryType.DIVIDEND,
            effective_date=pay_date,
            source_event_id=event.id,
            legs=[
                PostingLeg(account_id=cash_account.id, amount_money=amount),
                PostingLeg(account_id=receivable_account.id, amount_money=-amount),
            ],
            memo=f"dividend pay-date {pay_date} (S5 §6.1)",
        )

        obligation_event = record_inbound_event(
            self._uow,
            source=InboundEventSource.MARKETDATA,
            kind="dividend_pay_date_settlement_expected",
            payload={"customer_id": str(customer_id), "amount": str(amount)},
        )
        self._uow.settlement_obligations.add(
            SettlementObligation(
                journal_entry_id=entry.id,
                account_id=cash_account.id,
                amount_money=amount,
                expected_settlement_date=pay_date,
                source_event_id=obligation_event.id,
            )
        )

        RestatementService(self._uow).restate(
            customer_id=customer_id,
            affected_date=pay_date,
            trigger_type=RestatementTriggerType.LATE_DIVIDEND,
            source_event_id=entry.source_event_id,
        )
        return entry

    def apply_split(
        self, *, security_id: uuid.UUID, ratio: int | Decimal, effective_date: date
    ) -> list[JournalEntry]:
        """S5 §6.2: doubles (or `ratio`-multiplies) every open lot's quantity for `security_id`,
        posts a units-only entry per affected customer (S1 §3.4's worked example -- no money legs
        at all, since value and return must not move, FR-24)."""
        if ratio <= 1:
            raise ValueError(f"split ratio must be greater than 1, got {ratio!r}")

        entries: list[JournalEntry] = []
        for customer_id in self._uow.tax_lots.list_customers_holding(security_id):
            lots = self._uow.tax_lots.lock_open_for_security(customer_id, security_id)
            if not lots:
                continue

            prior_total = Units("0")
            for lot in lots:
                prior_total = prior_total + lot.quantity_remaining
            for lot in lots:
                lot.quantity_opened = lot.quantity_opened * ratio
                lot.quantity_remaining = lot.quantity_remaining * ratio

            added_units = prior_total * (ratio - 1)
            units_account = get_or_create_customer_account(
                self._uow,
                customer_id=customer_id,
                role=AccountRole.POSITION_UNITS,
                security_id=security_id,
            )
            event = record_inbound_event(
                self._uow,
                source=InboundEventSource.MARKETDATA,
                kind="split",
                payload={
                    "customer_id": str(customer_id),
                    "security_id": str(security_id),
                    "ratio": str(ratio),
                },
            )
            entry = self._posting_service.post(
                entry_type=JournalEntryType.SPLIT,
                effective_date=effective_date,
                source_event_id=event.id,
                legs=[PostingLeg(account_id=units_account.id, quantity_units=added_units)],
                memo=f"{ratio}-for-1 split, effective {effective_date} (S5 §6.2)",
            )
            entries.append(entry)

            RestatementService(self._uow).restate(
                customer_id=customer_id,
                affected_date=effective_date,
                trigger_type=RestatementTriggerType.SPLIT,
                source_event_id=entry.source_event_id,
            )
        return entries


__all__ = ["CorporateActionService"]
