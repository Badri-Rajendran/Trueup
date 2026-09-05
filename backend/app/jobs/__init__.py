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


def register_cli(app: Flask) -> None:
    """Called by the application factory when CLI wiring is enabled."""
    app.cli.add_command(jobs_cli)


__all__ = ["register_cli"]
