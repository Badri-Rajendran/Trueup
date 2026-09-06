"""`settlement_obligation` (S1 §4, ADR 2) — tracks whether the custodian confirmed a cash movement
the ledger already posted. Never posts to the ledger on a state transition.

`status` transitions exactly once, `pending -> confirmed | failed`, via a `BEFORE UPDATE` trigger; `DELETE` is revoked.
"""

from __future__ import annotations

import uuid
from datetime import (
    date,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    datetime,  # noqa: TC003
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, DateTime, ForeignKey, String, event
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class SettlementObligationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class SettlementObligation(Base):
    __tablename__ = "settlement_obligation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id"), nullable=False
    )
    amount_money: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    # Scheduling/risk input only -- never the confirmation trigger (ADR 2).
    expected_settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[SettlementObligationStatus] = mapped_column(
        SQLAlchemyEnum(
            SettlementObligationStatus,
            name="settlement_obligation_status",
            values_callable=enum_values,
        ),
        nullable=False,
        default=SettlementObligationStatus.PENDING,
        server_default=SettlementObligationStatus.PENDING.value,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_event.id"), nullable=False, unique=True
    )


_SINGLE_TRANSITION_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION settlement_obligation_single_transition() RETURNS trigger AS $$
    BEGIN
      IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'settlement_obligation %% is already terminal (%%) and cannot be updated',
          OLD.id, OLD.status;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_SINGLE_TRANSITION_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER settlement_obligation_before_update
      BEFORE UPDATE ON settlement_obligation
      FOR EACH ROW EXECUTE FUNCTION settlement_obligation_single_transition();
    """
)

for _ddl in (_SINGLE_TRANSITION_FUNCTION, _SINGLE_TRANSITION_TRIGGER):
    event.listen(SettlementObligation.__table__, "after_create", _ddl)

event.listen(
    SettlementObligation.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS settlement_obligation_before_update ON settlement_obligation;"
        "DROP FUNCTION IF EXISTS settlement_obligation_single_transition();"
    ),
)

# DELETE revoked; UPDATE stays granted for the one-time status transition above.
event.listen(
    SettlementObligation.__table__,
    "after_create",
    DDL("REVOKE DELETE ON settlement_obligation FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class SettlementObligationRepository(BaseRepository[SettlementObligation]):
    """No `customer_id_column`: per-customer reads compose with `posting`/`account`."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=SettlementObligation)

    def get_by_id(self, obligation_id: uuid.UUID) -> SettlementObligation | None:
        return self.session.query(SettlementObligation).filter_by(id=obligation_id).first()

    def confirm(self, obligation: SettlementObligation, *, confirmed_at: datetime) -> None:
        if obligation.status is not SettlementObligationStatus.PENDING:
            raise ValueError(
                f"settlement_obligation {obligation.id} is already {obligation.status}; "
                "status transitions exactly once (S1 §6)"
            )
        obligation.status = SettlementObligationStatus.CONFIRMED
        obligation.confirmed_at = confirmed_at

    def fail(
        self, obligation: SettlementObligation, *, failed_at: datetime, reason: str
    ) -> None:
        if obligation.status is not SettlementObligationStatus.PENDING:
            raise ValueError(
                f"settlement_obligation {obligation.id} is already {obligation.status}; "
                "status transitions exactly once (S1 §6)"
            )
        obligation.status = SettlementObligationStatus.FAILED
        obligation.failed_at = failed_at
        obligation.failure_reason = reason
