"""`target_weight` (S9 §3.2) — one row per `(model_portfolio, security)`, weighted to sum to
exactly `1.0` for every `model_portfolio_id`.

That sum-to-one invariant is a **deferred constraint trigger**, the same mechanism and the same
reasoning as S1 §3.4's money-sum-to-zero trigger (`app/models/ledger/posting.py`): it is a
*cross-row* invariant a plain `CHECK` cannot express (Postgres has no cross-row `CHECK`), and it
must be deferred to `COMMIT` rather than firing per-row, because populating a model's weights is
itself several inserts within one transaction — the sum is only ever meaningful once every row for
that `model_portfolio_id` has been written. Deleting the last row of a model (leaving `SUM = 0`) is
rejected the same way: a model portfolio with any target weights at all must sum to `1.0`, full
stop, so removing weights without replacing them in the same transaction is exactly as invalid as
never having balanced in the first place.
"""

from __future__ import annotations

import uuid
from decimal import Decimal  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from typing import TYPE_CHECKING

from sqlalchemy import DDL, ForeignKey, Numeric, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class TargetWeight(Base):
    __tablename__ = "target_weight"
    __table_args__ = (
        UniqueConstraint(
            "model_portfolio_id", "security_id", name="uq_target_weight_model_security"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_portfolio.id"), nullable=False
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security.id"), nullable=False
    )
    # A ratio, not a money/units/price dimension (ADR 16) -- ADR 16's value objects deliberately
    # don't cover this, matching `sub_period_return.return_pct`'s identical precedent.
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)


# --- target_weight_sum: cross-row sum-to-one invariant, deferred to COMMIT (S9 §3.2) ---------

_TARGET_WEIGHT_SUM_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION check_target_weight_sum() RETURNS trigger AS $$
    DECLARE
      mp_id uuid;
      total NUMERIC(5,4);
    BEGIN
      mp_id := COALESCE(NEW.model_portfolio_id, OLD.model_portfolio_id);
      SELECT COALESCE(SUM(weight_pct), 0) INTO total FROM target_weight
        WHERE model_portfolio_id = mp_id;
      IF total <> 1 THEN
        RAISE EXCEPTION 'model_portfolio %% target weights do not sum to 1.0 (got %%)',
          mp_id, total;
      END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_TARGET_WEIGHT_SUM_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE CONSTRAINT TRIGGER target_weight_sum
      AFTER INSERT OR UPDATE OR DELETE ON target_weight
      DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW
      EXECUTE FUNCTION check_target_weight_sum();
    """
)

for _ddl in (_TARGET_WEIGHT_SUM_FUNCTION, _TARGET_WEIGHT_SUM_TRIGGER):
    event.listen(TargetWeight.__table__, "after_create", _ddl)

event.listen(
    TargetWeight.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS target_weight_sum ON target_weight;"
        "DROP FUNCTION IF EXISTS check_target_weight_sum();"
    ),
)


class TargetWeightRepository(BaseRepository[TargetWeight]):
    """No `customer_id_column`: `target_weight` rows belong to a model, not a customer."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=TargetWeight)

    def list_for_model(self, model_portfolio_id: uuid.UUID) -> list[TargetWeight]:
        return (
            self.session.query(TargetWeight)
            .filter_by(model_portfolio_id=model_portfolio_id)
            .all()
        )


__all__ = ["TargetWeight", "TargetWeightRepository"]
