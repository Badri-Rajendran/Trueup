"""Flask CLI registration for scheduler-free jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
from flask.cli import AppGroup

from app.jobs.noop import NoopJob

if TYPE_CHECKING:
    from datetime import datetime

    from flask import Flask

    from app.integrations.ports import BrokerPort

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
    """Run `MorningReconciliationJob` (S7). No real custodian feed yet -- uses the simulator."""
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


@jobs_cli.command("seed-reference-data")
def seed_reference_data_command() -> None:
    """Seed demo reference data: 4 broad-market ETFs (`security`) and 4 named model portfolios
    with their `target_weight` rows (S9). NOT an investment-committee-approved allocation --
    `docs/specs/09-rebalancing.md`/`DECISION-LOG.md` explicitly defer that choice; this exists only
    to unblock the Portfolio page and order placement, which read those tables and find them
    empty in every environment today. Idempotent: safe to run more than once, including against a
    database another run already seeded -- reads whatever `DATABASE_URL*` this environment already
    has configured, so the identical command works in dev, staging, or the deployed instance.
    """
    from app.jobs.seed_reference_data import SeedReferenceDataJob

    result = SeedReferenceDataJob().run()
    click.echo(
        f"securities: created {list(result.securities_created)}, "
        f"already present {list(result.securities_skipped)}"
    )
    click.echo(
        f"model portfolios: created {list(result.model_portfolios_created)}, "
        f"already present {list(result.model_portfolios_skipped)}"
    )


@jobs_cli.command("outbox-worker")
def outbox_worker_command() -> None:
    """Always-on `job_outbox` drain process (S0 §9); blocks forever via `listen_forever`, routing
    `submit_order_to_broker`, `charge_fee`, and `process_inbound_event` to their handlers."""
    import os
    import uuid
    from datetime import UTC
    from datetime import datetime as dt
    from typing import Any

    from app.config import get_settings
    from app.core.db import DbRole
    from app.core.logging import get_logger
    from app.core.uow import SessionRole
    from app.models.ops import OpsUnitOfWork
    from app.models.ops.inbound_event import InboundEventSource
    from app.services.fees.fee_charge_outbox_handler import FeeChargeOutboxHandler
    from app.services.fees.uow import FeesUnitOfWork
    from app.services.intake.dispatch import InboundEventDispatcher
    from app.services.ledger.cash_policy_service import CashPolicyService
    from app.services.ops.outbox_task_router import OutboxTaskRouter
    from app.services.orders.approval_hold_service import ApprovalHoldService
    from app.services.orders.holds_provider import OrderHoldsProvider
    from app.services.orders.order_service import OrderService
    from app.services.orders.trade_update_handler import AlpacaTradeUpdateHandler
    from app.services.orders.uow import OrdersUnitOfWork
    from app.workers.outbox import OutboxWorker, create_listen_connection

    log = get_logger(__name__)
    settings = get_settings()

    def _ops_uow_factory() -> OpsUnitOfWork:
        return OpsUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER)

    def _orders_uow_factory() -> OrdersUnitOfWork:
        return OrdersUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER)

    def _fees_uow_factory() -> FeesUnitOfWork:
        return FeesUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER)

    dispatcher = InboundEventDispatcher()
    dispatcher.register(
        InboundEventSource.ALPACA,
        AlpacaTradeUpdateHandler(
            uow_factory=_orders_uow_factory, now=lambda: dt.now(UTC)
        ).handle,
    )
    dispatcher.register(InboundEventSource.STRIPE, lambda payload: None)
    dispatcher.register(InboundEventSource.PLAID, lambda payload: None)

    if settings.has_alpaca_credentials:
        from app.integrations.alpaca.broker_adapter import AlpacaBrokerAdapter

        broker_port: BrokerPort = AlpacaBrokerAdapter(
            api_key_id=settings.alpaca_api_key_id.get_secret_value(),  # type: ignore[union-attr]
            api_secret_key=settings.alpaca_api_secret_key.get_secret_value(),  # type: ignore[union-attr]
        )
    else:
        from app.integrations.fake.fake_broker import FakeBrokerAdapter

        log.warning(
            "outbox_worker_broker_credentials_missing",
            detail="ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY unset -- submitting orders against "
            "FakeBrokerAdapter, not a real (paper) broker",
        )
        broker_port = FakeBrokerAdapter()

    fee_handler: FeeChargeOutboxHandler | None = None
    if settings.stripe_secret_key is not None:
        from app.integrations.stripe.billing_adapter import StripeBillingAdapter

        fee_handler = FeeChargeOutboxHandler(
            uow_factory=_fees_uow_factory,
            payment_port=StripeBillingAdapter(api_key=settings.stripe_secret_key.get_secret_value()),
            dunning_max_attempts=settings.dunning_max_attempts,
        )
    else:
        log.warning(
            "outbox_worker_stripe_credentials_missing",
            detail="STRIPE_SECRET_KEY unset -- charge_fee outbox tasks will fail until it is set",
        )

    def _submit_order_to_broker(payload: dict[str, Any]) -> None:
        with _orders_uow_factory() as uow:
            service = OrderService(
                uow,
                hold_service=ApprovalHoldService(uow),
                cash_policy=CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow)),
                approval_threshold_usd=settings.order_approval_threshold_usd,
            )
            service.submit_to_broker(
                uuid.UUID(str(payload["order_id"])),
                symbol=str(payload["symbol"]),
                broker=broker_port,
            )
            uow.commit()

    def _charge_fee(payload: dict[str, Any]) -> None:
        if fee_handler is None:
            raise RuntimeError("STRIPE_SECRET_KEY is required to process charge_fee outbox tasks")
        fee_handler.handle(task="charge_fee", payload=payload)

    def _process_inbound_event(payload: dict[str, Any]) -> None:
        with _ops_uow_factory() as uow:
            dispatcher.handle(task="process_inbound_event", payload=payload, uow=uow.inbound_events)
            uow.commit()

    router = OutboxTaskRouter(
        routes={
            "submit_order_to_broker": _submit_order_to_broker,
            "charge_fee": _charge_fee,
            "process_inbound_event": _process_inbound_event,
        }
    )
    worker = OutboxWorker(
        uow_factory=_ops_uow_factory,
        handler=router,
        worker_id=f"outbox-worker-{os.getpid()}",
        max_attempts=settings.outbox_max_attempts,
    )
    connection = create_listen_connection(settings.database_url_worker.get_secret_value())
    worker.listen_forever(connection)


@jobs_cli.command("create-staff")
@click.option("--email", required=True, help="Staff member's login email.")
@click.option(
    "--role",
    type=click.Choice(["adviser", "admin"]),
    required=True,
    help="adviser or admin (S0 §7.2).",
)
@click.password_option(
    "--password",
    prompt="Password",
    confirmation_prompt=True,
    hide_input=True,
    help="Prompted for, never passed as an argument -- keeps it out of shell history and logs.",
)
def create_staff_command(email: str, role: str, password: str) -> None:
    """Provision a staff (adviser/admin) account. There is deliberately no staff self-registration
    route -- `/auth/register` creates customers only -- so this is the sole way a staff principal
    comes into existence, and with it the only way the admin screens become reachable.

    The account is created WITHOUT a TOTP secret: staff login is MFA-gated, and `/auth/mfa/enroll`
    enrolls the authenticator on first login. Fails rather than overwriting if the email is already
    registered as either a customer or staff.
    """
    from app.jobs.create_staff import CreateStaffJob, EmailAlreadyRegisteredError
    from app.models.identity.staff import StaffRole

    try:
        result = CreateStaffJob().run(
            email=email, password=password, role=StaffRole(role)
        )
    except EmailAlreadyRegisteredError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"created staff {result.email} ({result.role.value}) id={result.staff_id}")
    click.echo("Enroll MFA at first login -- the account has no authenticator secret yet.")


def register_cli(app: Flask) -> None:
    """Called by the application factory when CLI wiring is enabled."""
    app.cli.add_command(jobs_cli)


__all__ = ["register_cli"]
