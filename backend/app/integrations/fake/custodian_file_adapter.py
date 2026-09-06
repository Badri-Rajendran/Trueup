"""`CustodianFileSimulatorAdapter` (S7 §9, FR-33) — the clearly-labelled custodian-file simulator.

Unlike this package's other fakes, this is a production-quality simulator the running system
actually calls (FR-33): it reads Trueup's own internal state via the same
`app.services.reconciliation.internal_state` readers `ReconciliationService` uses. `inject_*`
methods queue a mutation for the next `fetch_files()`; `inject_corrected_price` instead posts
directly to `daily_close` with `source='simulated'`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.integrations.ports import (
    CustodianCashRow,
    CustodianFileSet,
    CustodianPositionRow,
    CustodianTransactionRow,
    CustodianTransactionType,
)
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.restatement.restatement_event import RestatementTriggerType
from app.services.identity.null_holds_provider import NullHoldsProvider
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.reconciliation.internal_state import (
    read_customer_ids,
    read_internal_positions,
    read_internal_transactions,
)
from app.services.restatement.restatement_service import RestatementService

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from app.core.money import Money, Price, Units
    from app.services.reconciliation.uow import ReconciliationUnitOfWork

_ENTRY_TYPE_TO_CUSTODIAN_TRANSACTION_TYPE: dict[JournalEntryType, CustodianTransactionType] = {
    JournalEntryType.TRADE_BUY: CustodianTransactionType.TRADE,
    JournalEntryType.TRADE_SELL: CustodianTransactionType.TRADE,
    JournalEntryType.DEPOSIT: CustodianTransactionType.DEPOSIT,
    JournalEntryType.WITHDRAWAL: CustodianTransactionType.WITHDRAWAL,
    JournalEntryType.DIVIDEND: CustodianTransactionType.DIVIDEND,
    JournalEntryType.FEE_ADJUSTMENT: CustodianTransactionType.FEE,
}
"""Must stay in sync with `internal_state.CUSTODIAN_OBSERVABLE_ENTRY_TYPES`'s key set (S7 §4)."""


class CustodianFileSimulatorAdapter:
    """`CustodianFilePort` implementation. No real custodian feed is contracted yet (S7 §12)."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], ReconciliationUnitOfWork],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._now = now
        self._tampered_positions: dict[tuple[uuid.UUID, uuid.UUID], Units] = {}
        self._late_dividends: list[CustodianTransactionRow] = []

    def inject_tampered_position(
        self, *, customer_id: uuid.UUID, security_id: uuid.UUID, wrong_quantity: Units
    ) -> None:
        """FR-32's live-fire mechanism (S7 §9): overwrites one row in the next `positions.csv`."""
        self._tampered_positions[(customer_id, security_id)] = wrong_quantity

    def clear_injections(self) -> None:
        """Resets every queued tamper/injection, so a caller can run a clean file afterward."""
        self._tampered_positions.clear()
        self._late_dividends.clear()

    def inject_late_dividend(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        amount: Money,
        effective_date: date,
    ) -> None:
        """Adds a transaction row with no corresponding internal entry yet (S7 §9); the next
        `fetch_files()` includes it, correctly flagged `unmatched_custodian_transaction`."""
        self._late_dividends.append(
            CustodianTransactionRow(
                custodian_transaction_id=f"simulated-dividend:{uuid.uuid4()}",
                customer_id=customer_id,
                security_id=security_id,
                transaction_type=CustodianTransactionType.DIVIDEND,
                amount_money=amount,
                quantity=None,
                effective_date=effective_date,
            )
        )

    def inject_corrected_price(
        self, *, security_id: uuid.UUID, market_date: date, new_close: Price
    ) -> None:
        """S7 §9: bypasses the custodian file, posts a second confirmed `daily_close` row with
        `source='simulated'` (NFR-12), and fans `RestatementService.restate()` out to every
        customer holding `security_id` in the same transaction."""
        with self._uow_factory() as uow:
            event = InboundEvent(
                source=InboundEventSource.MARKETDATA,
                source_event_id=f"simulated-corrected-close:{uuid.uuid4()}",
                payload={
                    "security_id": str(security_id),
                    "market_date": market_date.isoformat(),
                    "new_close": str(new_close),
                },
                signature_verified=True,
            )
            uow.inbound_events.add(event)
            uow.session.flush()

            uow.daily_closes.add(
                DailyClose(
                    security_id=security_id,
                    market_date=market_date,
                    close_price=new_close,
                    source=MarketDataSource.SIMULATED,
                    status=DailyCloseStatus.CONFIRMED,
                    recorded_at=self._now(),
                )
            )

            restatement_service = RestatementService(uow)
            for customer_id in uow.tax_lots.list_customers_holding(security_id):
                restatement_service.restate(
                    customer_id=customer_id,
                    affected_date=market_date,
                    trigger_type=RestatementTriggerType.CORRECTED_CLOSE,
                    source_event_id=event.id,
                )

            uow.commit()

    def fetch_files(self, *, market_date: date) -> CustodianFileSet:
        with self._uow_factory() as uow:
            positions = self._generate_positions(uow, market_date)
            cash = self._generate_cash(uow, market_date)
            transactions = self._generate_transactions(uow, market_date)
        return CustodianFileSet(
            positions=positions,
            cash=cash,
            transactions=[*transactions, *self._late_dividends],
            is_simulated=True,
        )

    def _generate_positions(
        self, uow: ReconciliationUnitOfWork, market_date: date
    ) -> list[CustodianPositionRow]:
        internal = read_internal_positions(uow, market_date)
        rows: dict[tuple[uuid.UUID, uuid.UUID], CustodianPositionRow] = {
            key: CustodianPositionRow(
                customer_id=key[0], security_id=key[1], quantity=quantity, as_of_date=market_date
            )
            for key, quantity in internal.items()
        }
        for (customer_id, security_id), wrong_quantity in self._tampered_positions.items():
            rows[(customer_id, security_id)] = CustodianPositionRow(
                customer_id=customer_id,
                security_id=security_id,
                quantity=wrong_quantity,
                as_of_date=market_date,
            )
        return list(rows.values())

    def _generate_cash(
        self, uow: ReconciliationUnitOfWork, market_date: date
    ) -> list[CustodianCashRow]:
        cash_service = CashPolicyService(uow, holds_provider=NullHoldsProvider())
        return [
            CustodianCashRow(
                customer_id=customer_id,
                settled_cash=cash_service.settled_cash(customer_id),
                as_of_date=market_date,
            )
            for customer_id in read_customer_ids(uow)
        ]

    def _generate_transactions(
        self, uow: ReconciliationUnitOfWork, market_date: date
    ) -> list[CustodianTransactionRow]:
        internal = read_internal_transactions(uow, market_date)
        return [
            CustodianTransactionRow(
                custodian_transaction_id=source_event_id,
                customer_id=snapshot.customer_id,
                security_id=snapshot.security_id,
                transaction_type=_ENTRY_TYPE_TO_CUSTODIAN_TRANSACTION_TYPE[snapshot.entry_type],
                amount_money=snapshot.amount_money,
                quantity=snapshot.quantity,
                effective_date=snapshot.effective_date,
            )
            for source_event_id, snapshot in internal.items()
        ]


__all__ = ["CustodianFileSimulatorAdapter"]
