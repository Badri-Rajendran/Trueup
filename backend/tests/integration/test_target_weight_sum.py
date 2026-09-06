"""S9 §3.2's cross-row sum-to-one invariant on `target_weight` -- a deferred constraint trigger,
tested the same way S1's ledger-balance trigger is tested
(`tests/integration/test_ledger_balance.py`): a deliberately unbalanced model definition must
fail at `COMMIT`, not at flush, so this runs under `db_committing` (S9 §9)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight

REBALANCE_MODEL_TABLES = [Security.__table__, ModelPortfolio.__table__, TargetWeight.__table__]


@pytest.fixture
def rebalance_model_tables(owner_engine):
    for table in REBALANCE_MODEL_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(REBALANCE_MODEL_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


pytestmark = pytest.mark.usefixtures("rebalance_model_tables")


def _seed_model_and_securities(session):
    model = ModelPortfolio(name="Test Model")
    session.add(model)
    security_one = Security(symbol="AGG", name="Agg Co.", asset_class=SecurityAssetClass.BOND)
    security_two = Security(symbol="SPY", name="SPY Co.", asset_class=SecurityAssetClass.EQUITY)
    session.add_all([security_one, security_two])
    session.flush()
    return model, security_one, security_two


def test_target_weight_sum_to_one_trigger_fires_at_commit_not_at_flush(db_committing) -> None:
    model, security_one, security_two = _seed_model_and_securities(db_committing)

    # Deliberately unbalanced: 0.60 + 0.30 = 0.90, not 1.0. Inserted directly, matching
    # test_ledger_balance.py's own pattern of bypassing any application-layer service.
    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security_one.id, weight_pct=Decimal("0.60")
        )
    )
    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security_two.id, weight_pct=Decimal("0.30")
        )
    )
    db_committing.flush()  # must NOT raise -- the trigger is deferred to COMMIT.

    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


def test_a_balanced_model_commits_cleanly(db_committing) -> None:
    model, security_one, security_two = _seed_model_and_securities(db_committing)

    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security_one.id, weight_pct=Decimal("0.60")
        )
    )
    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security_two.id, weight_pct=Decimal("0.40")
        )
    )

    db_committing.commit()  # must not raise


def test_deleting_a_weight_without_replacing_it_reopens_the_violation(db_committing) -> None:
    """S9 §3.2: a model portfolio with any target weights at all must sum to 1.0 -- removing a
    row without a replacement in the same transaction is exactly as invalid as never having
    balanced (this module's own docstring)."""
    model, security_one, security_two = _seed_model_and_securities(db_committing)
    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security_one.id, weight_pct=Decimal("0.60")
        )
    )
    weight_two = TargetWeight(
        model_portfolio_id=model.id, security_id=security_two.id, weight_pct=Decimal("0.40")
    )
    db_committing.add(weight_two)
    db_committing.commit()

    db_committing.delete(weight_two)
    db_committing.flush()  # deferred -- must not raise yet

    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()
