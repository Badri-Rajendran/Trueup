"""`SeedReferenceDataJob` against real PostgreSQL -- proves the actual `security`/`model_portfolio`/
`target_weight` writes (including the deferred `check_target_weight_sum` trigger, S9 §3.2) commit
cleanly, and that a second run is a genuine no-op rather than a duplicate/constraint-violation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.db import DbRole
from app.core.uow import SessionRole
from app.jobs.seed_reference_data import MODEL_PORTFOLIOS, SECURITIES, SeedReferenceDataJob
from app.models.marketdata.security import Security
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.rebalance.uow import RebalanceUnitOfWork

SEED_TABLES = [
    Security.__table__,
    ModelPortfolio.__table__,
    TargetWeight.__table__,
]


@pytest.fixture
def seed_tables(owner_engine):
    for table in SEED_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(SEED_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


pytestmark = pytest.mark.usefixtures("seed_tables")


def _owner_uow() -> RebalanceUnitOfWork:
    return RebalanceUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def test_run_creates_all_securities_and_model_portfolios() -> None:
    result = SeedReferenceDataJob(uow_factory=_owner_uow).run()

    assert set(result.securities_created) == {spec.symbol for spec in SECURITIES}
    assert result.securities_skipped == ()
    assert set(result.model_portfolios_created) == {spec.name for spec in MODEL_PORTFOLIOS}
    assert result.model_portfolios_skipped == ()

    with _owner_uow() as uow:
        for spec in SECURITIES:
            security = uow.securities.get_by_symbol(spec.symbol)
            assert security is not None
            assert security.name == spec.name
            assert security.asset_class == spec.asset_class

        for spec in MODEL_PORTFOLIOS:
            model = uow.model_portfolios.get_by_name(spec.name)
            assert model is not None
            weights = uow.target_weights.list_for_model(model.id)
            assert len(weights) == len(spec.weights)


def test_every_model_portfolios_weights_sum_to_exactly_one() -> None:
    SeedReferenceDataJob(uow_factory=_owner_uow).run()

    with _owner_uow() as uow:
        for spec in MODEL_PORTFOLIOS:
            model = uow.model_portfolios.get_by_name(spec.name)
            assert model is not None
            total = sum(
                (tw.weight_pct for tw in uow.target_weights.list_for_model(model.id)),
                start=Decimal("0"),
            )
            assert total == Decimal("1.0000")


def test_running_twice_creates_nothing_new() -> None:
    SeedReferenceDataJob(uow_factory=_owner_uow).run()

    with _owner_uow() as uow:
        security_count_before = len(
            [uow.securities.get_by_symbol(spec.symbol) for spec in SECURITIES]
        )
        model_ids_before = {
            spec.name: uow.model_portfolios.get_by_name(spec.name).id  # type: ignore[union-attr]
            for spec in MODEL_PORTFOLIOS
        }

    second_result = SeedReferenceDataJob(uow_factory=_owner_uow).run()

    assert second_result.securities_created == ()
    assert set(second_result.securities_skipped) == {spec.symbol for spec in SECURITIES}
    assert second_result.model_portfolios_created == ()
    assert set(second_result.model_portfolios_skipped) == {spec.name for spec in MODEL_PORTFOLIOS}

    with _owner_uow() as uow:
        security_count_after = len(
            [uow.securities.get_by_symbol(spec.symbol) for spec in SECURITIES]
        )
        assert security_count_after == security_count_before

        for spec in MODEL_PORTFOLIOS:
            model = uow.model_portfolios.get_by_name(spec.name)
            assert model is not None
            # Same row, not a duplicate with a different id.
            assert model.id == model_ids_before[spec.name]
            weights = uow.target_weights.list_for_model(model.id)
            assert len(weights) == len(spec.weights)


def test_seeding_onto_a_partially_seeded_database_only_fills_the_gap() -> None:
    """A security created out-of-band (e.g. by another feature's own setup) is left alone and
    reused, not duplicated -- the upsert-by-symbol path, not just the whole-job-already-ran path."""
    with _owner_uow() as uow:
        pre_existing = Security(
            symbol=SECURITIES[0].symbol,
            name="Pre-existing name, deliberately different",
            asset_class=SECURITIES[0].asset_class,
        )
        uow.securities.add(pre_existing)
        uow.commit()

    result = SeedReferenceDataJob(uow_factory=_owner_uow).run()

    assert SECURITIES[0].symbol in result.securities_skipped
    assert SECURITIES[0].symbol not in result.securities_created

    with _owner_uow() as uow:
        security = uow.securities.get_by_symbol(SECURITIES[0].symbol)
        assert security is not None
        assert security.id == pre_existing.id
        assert security.name == "Pre-existing name, deliberately different"
