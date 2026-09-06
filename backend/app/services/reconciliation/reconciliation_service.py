"""`ReconciliationService` (S7 §6) — the three matching loops plus the holiday short-circuit.

Reuses `app.services.reconciliation.internal_state`'s readers (shared with the custodian-file
simulator, S7 §9) rather than re-deriving "what does Trueup's ledger currently say" independently.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from app.core.money import Money, Units
from app.models.reconciliation.custodian_file_row import CustodianFileRow, CustodianFileType
from app.models.reconciliation.reconciliation_break import (
    ReconciliationBreak,
    ReconciliationBreakType,
)
from app.services.identity.null_holds_provider import NullHoldsProvider
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.reconciliation.internal_state import (
    InternalTransactionSnapshot,
    read_customer_ids,
    read_internal_positions,
    read_internal_transactions,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from app.core.clock import MarketClock
    from app.integrations.ports import CustodianFileSet, CustodianTransactionRow
    from app.services.reconciliation.uow import ReconciliationUnitOfWork


class ReconciliationService:
    def __init__(
        self,
        uow: ReconciliationUnitOfWork,
        *,
        market_clock: MarketClock,
        now: Callable[[], datetime],
    ) -> None:
        self._uow = uow
        self._market_clock = market_clock
        self._now = now

    def run_morning_reconciliation(
        self, *, market_date: date, file_set: CustodianFileSet
    ) -> list[ReconciliationBreak]:
        """S7 §6's pseudocode, literally: import the batch, short-circuit on a holiday (ADR 12),
        then run the three independent matching loops. Stages every opened break via
        `uow.reconciliation_breaks.add()` -- the caller commits (S0 §5's one-commit-per-operation
        rule; this service never commits its own transaction)."""
        if not self._market_clock.is_trading_day(market_date):
            # S7 §6/§10 case 1 (ADR 12): a holiday is never a break, full stop -- not "compared
            # and found clean." No raw rows are persisted either; there was never a real morning
            # file to preserve.
            return []

        import_batch_id = uuid.uuid4()
        opened_at = self._now()
        self._persist_raw_rows(file_set, import_batch_id=import_batch_id, imported_at=opened_at)

        breaks: list[ReconciliationBreak] = [
            *self._match_positions(
                file_set,
                market_date=market_date,
                import_batch_id=import_batch_id,
                opened_at=opened_at,
            ),
            *self._match_cash(file_set, import_batch_id=import_batch_id, opened_at=opened_at),
            *self._match_transactions(
                file_set,
                market_date=market_date,
                import_batch_id=import_batch_id,
                opened_at=opened_at,
            ),
        ]
        for break_row in breaks:
            self._uow.reconciliation_breaks.add(break_row)
        return breaks

    # --- raw preservation (S7 §3) ---------------------------------------------------------

    def _persist_raw_rows(
        self, file_set: CustodianFileSet, *, import_batch_id: uuid.UUID, imported_at: datetime
    ) -> None:
        for position_row in file_set.positions:
            self._uow.custodian_file_rows.add(
                CustodianFileRow(
                    file_type=CustodianFileType.POSITIONS,
                    raw_row={
                        "customer_id": str(position_row.customer_id),
                        "security_id": str(position_row.security_id),
                        "quantity": str(position_row.quantity),
                        "as_of_date": position_row.as_of_date.isoformat(),
                    },
                    import_batch_id=import_batch_id,
                    is_simulated=file_set.is_simulated,
                    imported_at=imported_at,
                )
            )
        for cash_row in file_set.cash:
            self._uow.custodian_file_rows.add(
                CustodianFileRow(
                    file_type=CustodianFileType.CASH,
                    raw_row={
                        "customer_id": str(cash_row.customer_id),
                        "settled_cash": str(cash_row.settled_cash),
                        "as_of_date": cash_row.as_of_date.isoformat(),
                    },
                    import_batch_id=import_batch_id,
                    is_simulated=file_set.is_simulated,
                    imported_at=imported_at,
                )
            )
        for transaction_row in file_set.transactions:
            self._uow.custodian_file_rows.add(
                CustodianFileRow(
                    file_type=CustodianFileType.TRANSACTIONS,
                    raw_row=_serialize_transaction_row(transaction_row),
                    import_batch_id=import_batch_id,
                    is_simulated=file_set.is_simulated,
                    imported_at=imported_at,
                )
            )

    # --- positions (S7 §4/§6) -------------------------------------------------------------

    def _match_positions(
        self,
        file_set: CustodianFileSet,
        *,
        market_date: date,
        import_batch_id: uuid.UUID,
        opened_at: datetime,
    ) -> list[ReconciliationBreak]:
        internal = read_internal_positions(self._uow, market_date)
        from_file = {
            (row.customer_id, row.security_id): row.quantity for row in file_set.positions
        }
        breaks = []
        for customer_id, security_id in internal.keys() | from_file.keys():
            internal_qty = internal.get((customer_id, security_id), Units("0"))
            file_qty = from_file.get((customer_id, security_id), Units("0"))
            if internal_qty == file_qty:
                continue
            breaks.append(
                ReconciliationBreak(
                    break_type=ReconciliationBreakType.POSITION_MISMATCH,
                    customer_id=customer_id,
                    expected={"security_id": str(security_id), "quantity": str(internal_qty)},
                    actual={"security_id": str(security_id), "quantity": str(file_qty)},
                    opened_at=opened_at,
                    import_batch_id=import_batch_id,
                )
            )
        return breaks

    # --- cash (S7 §4/§6) -------------------------------------------------------------------

    def _match_cash(
        self, file_set: CustodianFileSet, *, import_batch_id: uuid.UUID, opened_at: datetime
    ) -> list[ReconciliationBreak]:
        cash_service = CashPolicyService(self._uow, holds_provider=NullHoldsProvider())
        from_file = {row.customer_id: row.settled_cash for row in file_set.cash}
        customer_ids = read_customer_ids(self._uow) | from_file.keys()
        breaks = []
        for customer_id in customer_ids:
            internal_cash = cash_service.settled_cash(customer_id)
            file_cash = from_file.get(customer_id, Money("0.00"))
            if internal_cash == file_cash:
                continue
            breaks.append(
                ReconciliationBreak(
                    break_type=ReconciliationBreakType.CASH_MISMATCH,
                    customer_id=customer_id,
                    expected={"settled_cash": str(internal_cash)},
                    actual={"settled_cash": str(file_cash)},
                    opened_at=opened_at,
                    import_batch_id=import_batch_id,
                )
            )
        return breaks

    # --- transactions (S7 §4/§6) ------------------------------------------------------------

    def _match_transactions(
        self,
        file_set: CustodianFileSet,
        *,
        market_date: date,
        import_batch_id: uuid.UUID,
        opened_at: datetime,
    ) -> list[ReconciliationBreak]:
        from_file = {row.custodian_transaction_id: row for row in file_set.transactions}
        internal = read_internal_transactions(self._uow, market_date)

        breaks = []
        for custodian_transaction_id, row in from_file.items():
            if custodian_transaction_id in internal:
                continue
            breaks.append(
                ReconciliationBreak(
                    break_type=ReconciliationBreakType.UNMATCHED_CUSTODIAN_TRANSACTION,
                    customer_id=row.customer_id,
                    expected=None,
                    actual=_serialize_transaction_row(row),
                    opened_at=opened_at,
                    import_batch_id=import_batch_id,
                )
            )
        for source_event_id, snapshot in internal.items():
            if source_event_id in from_file:
                continue
            breaks.append(
                ReconciliationBreak(
                    break_type=ReconciliationBreakType.UNMATCHED_INTERNAL_TRANSACTION,
                    customer_id=snapshot.customer_id,
                    expected=_serialize_internal_snapshot(snapshot),
                    actual=None,
                    opened_at=opened_at,
                    import_batch_id=import_batch_id,
                )
            )
        return breaks


def _serialize_transaction_row(row: CustodianTransactionRow) -> dict[str, Any]:
    return {
        "custodian_transaction_id": row.custodian_transaction_id,
        "customer_id": str(row.customer_id) if row.customer_id is not None else None,
        "security_id": str(row.security_id) if row.security_id is not None else None,
        "transaction_type": row.transaction_type.value,
        "amount_money": str(row.amount_money),
        "quantity": str(row.quantity) if row.quantity is not None else None,
        "effective_date": row.effective_date.isoformat(),
    }


def _serialize_internal_snapshot(snapshot: InternalTransactionSnapshot) -> dict[str, Any]:
    return {
        "journal_entry_id": str(snapshot.journal_entry_id),
        "entry_type": snapshot.entry_type.value,
        "customer_id": str(snapshot.customer_id) if snapshot.customer_id is not None else None,
        "security_id": str(snapshot.security_id) if snapshot.security_id is not None else None,
        "amount_money": str(snapshot.amount_money),
        "quantity": str(snapshot.quantity) if snapshot.quantity is not None else None,
        "effective_date": snapshot.effective_date.isoformat(),
    }


__all__ = ["ReconciliationService"]
