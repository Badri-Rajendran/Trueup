"""Flask CLI registration for scheduler-free jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
from flask.cli import AppGroup

from app.jobs.noop import NoopJob

if TYPE_CHECKING:
    from datetime import datetime

    from flask import Flask

jobs_cli = AppGroup("jobs")


@jobs_cli.command("noop")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def noop_command(market_date: datetime) -> None:
    """Run the example job through the identical interface Azure invokes."""
    outcome = NoopJob().run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("daily-valuation")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def daily_valuation_command(market_date: datetime) -> None:
    """Run `DailyValuationJob` (S4) through the identical interface Azure invokes."""
    from app.config import get_settings
    from app.integrations.alpaca.calendar_adapter import AlpacaCalendarAdapter
    from app.integrations.alpaca.market_data_adapter import AlpacaMarketDataAdapter
    from app.jobs.daily_valuation import DailyValuationJob

    settings = get_settings()
    if not settings.has_alpaca_credentials:
        raise RuntimeError("ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY are required to run this job")
    api_key_id = settings.alpaca_api_key_id.get_secret_value()  # type: ignore[union-attr]
    api_secret_key = settings.alpaca_api_secret_key.get_secret_value()  # type: ignore[union-attr]

    job = DailyValuationJob(
        market_data_port=AlpacaMarketDataAdapter(
            api_key_id=api_key_id, api_secret_key=api_secret_key
        ),
        calendar_port=AlpacaCalendarAdapter(api_key_id=api_key_id, api_secret_key=api_secret_key),
    )
    outcome = job.run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("snapshot-cross-check-sweep")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def snapshot_cross_check_sweep_command(market_date: datetime) -> None:
    """Run `SnapshotCrossCheckJob` (S6 §6/§11) through the identical interface Azure invokes."""
    from app.jobs.snapshot_cross_check import SnapshotCrossCheckJob

    outcome = SnapshotCrossCheckJob().run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("morning-reconciliation")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def morning_reconciliation_command(market_date: datetime) -> None:
    """Run `MorningReconciliationJob` (S7) through the identical interface Azure invokes.

    No real custodian feed is contracted yet (S7 §12) -- the simulator is the only
    `CustodianFilePort` implementation today, exactly as NFR-12 anticipates ("simulated is fine").
    Swap in a real adapter here, with no change to the job itself, once one exists.
    """
    from app.core.db import DbRole
    from app.core.uow import SessionRole
    from app.integrations.fake.custodian_file_adapter import CustodianFileSimulatorAdapter
    from app.jobs.morning_reconciliation import MorningReconciliationJob
    from app.services.reconciliation.uow import ReconciliationUnitOfWork

    def _reconciliation_uow_factory() -> ReconciliationUnitOfWork:
        return ReconciliationUnitOfWork(
            customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
        )

    job = MorningReconciliationJob(
        custodian_file_port=CustodianFileSimulatorAdapter(
            uow_factory=_reconciliation_uow_factory
        ),
    )
    outcome = job.run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("monthly-rebalance")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def monthly_rebalance_command(market_date: datetime) -> None:
    """Run `MonthlyRebalanceJob` (S9) through the identical interface Azure invokes."""
    from app.jobs.monthly_rebalance import MonthlyRebalanceJob

    outcome = MonthlyRebalanceJob().run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("daily-fee-accrual")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def daily_fee_accrual_command(market_date: datetime) -> None:
    """Run `DailyFeeAccrualJob` (S10 §4) through the identical interface Azure invokes."""
    from app.jobs.daily_fee_accrual import DailyFeeAccrualJob

    outcome = DailyFeeAccrualJob().run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("monthly-fee-charge")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def monthly_fee_charge_command(market_date: datetime) -> None:
    """Run `MonthlyFeeChargeJob` (S10 §5) through the identical interface Azure invokes."""
    from app.jobs.monthly_fee_charge import MonthlyFeeChargeJob

    outcome = MonthlyFeeChargeJob().run(market_date=market_date.date())
    click.echo(outcome.value)


@jobs_cli.command("dunning-retry")
@click.option("--market-date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
def dunning_retry_command(market_date: datetime) -> None:
    """Run `DunningRetryJob` (S10 §5) through the identical interface Azure invokes."""
    from app.config import get_settings
    from app.core.db import DbRole
    from app.core.uow import SessionRole
    from app.integrations.stripe.billing_adapter import StripeBillingAdapter
    from app.jobs.dunning_retry import DunningRetryJob
    from app.services.fees.fee_charge_outbox_handler import FeeChargeOutboxHandler
    from app.services.fees.uow import FeesUnitOfWork

    settings = get_settings()
    if settings.stripe_secret_key is None:
        raise RuntimeError("STRIPE_SECRET_KEY is required to run this job")

    def _fees_uow_factory() -> FeesUnitOfWork:
        return FeesUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER)

    outbox_handler = FeeChargeOutboxHandler(
        uow_factory=_fees_uow_factory,
        payment_port=StripeBillingAdapter(api_key=settings.stripe_secret_key.get_secret_value()),
        dunning_max_attempts=settings.dunning_max_attempts,
    )
    outcome = DunningRetryJob(outbox_handler=outbox_handler).run(market_date=market_date.date())
    click.echo(outcome.value)


def register_cli(app: Flask) -> None:
    """Called by the application factory when CLI wiring is enabled."""
    app.cli.add_command(jobs_cli)


__all__ = ["register_cli"]
