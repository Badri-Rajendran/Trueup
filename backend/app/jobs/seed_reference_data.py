"""Demo reference data for grading/demonstration -- NOT an investment-committee-approved
allocation.

`docs/specs/09-rebalancing.md:27-29` and `DECISION-LOG.md:176-178` are explicit that model
composition is "a product/investment-committee decision this spec doesn't invent" -- so nothing
in this codebase ever seeded `security`/`model_portfolio`/`target_weight`, leaving all three empty
in every environment (dev, staging, and the deployed Azure instance alike) and leaving the
Portfolio page and order placement with nothing to read (FR-7). This job exists only to unblock
that with real, demo-labelled reference data: four broad-market ETFs and four named model
allocations. Swapping this for whatever an investment committee actually approves is a follow-up
this job deliberately does not pre-empt -- it is reference data an operator can re-run, not a
migration that locks the choice in.

`flask jobs seed-reference-data` (`app/jobs/__init__.py`) -- reads whatever `DATABASE_URL*` the
running environment already has configured (via `RebalanceUnitOfWork`/`app/core/db.py`), so the
identical command seeds dev, staging, or the live deployment with no connection detail hard-coded
here.

**Idempotent.** A security already present (matched on `symbol`, which already carries a DB-level
`UNIQUE` constraint -- `app/models/marketdata/security.py`) or a model portfolio already present
(matched on `name`, an application-layer check only -- `model_portfolio.name` carries no DB-level
uniqueness) is left untouched. Running this twice, including against a database another run (or
another operator) already seeded, creates nothing new and raises nothing.

Not a `ScheduledJob` (`app/jobs/base.py`): that abstraction is for a market-date-anchored,
recurring cadence (S0 §9/ADR 13) -- a required `--market-date` and a `job_run` row would be a
category error for a one-time/rerunnable admin bootstrap. This follows the one other command in
`app/jobs/__init__.py` that isn't a `ScheduledJob` either -- `outbox-worker`, also infrastructure
bootstrapping rather than a per-market-date business operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.db import DbRole
from app.core.logging import get_logger
from app.core.uow import SessionRole
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.rebalance.uow import RebalanceUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)


@dataclass(frozen=True)
class _SecuritySpec:
    symbol: str
    name: str
    asset_class: SecurityAssetClass


@dataclass(frozen=True)
class _ModelPortfolioSpec:
    name: str
    weights: dict[str, Decimal]


# Four broad-market ETFs: US total-market equity, international equity, US total-bond-market, and
# a short-duration Treasury as the "cash-like" holding -- enough range to give each model below a
# genuinely distinct allocation shape. Demo data, not a vetted instrument list.
SECURITIES: tuple[_SecuritySpec, ...] = (
    _SecuritySpec("VTI", "Vanguard Total Stock Market ETF", SecurityAssetClass.EQUITY),
    _SecuritySpec("VXUS", "Vanguard Total International Stock ETF", SecurityAssetClass.EQUITY),
    _SecuritySpec("BND", "Vanguard Total Bond Market ETF", SecurityAssetClass.BOND),
    _SecuritySpec("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF", SecurityAssetClass.BOND),
)

# Demo allocations only -- not investment-committee-approved. Each model's weights sum to exactly
# 1.0000; `target_weight`'s deferred `check_target_weight_sum` trigger
# (`app/models/rebalance/target_weight.py`) enforces that at COMMIT, so a typo here fails the whole
# seed run loudly instead of silently landing a broken model.
MODEL_PORTFOLIOS: tuple[_ModelPortfolioSpec, ...] = (
    _ModelPortfolioSpec(
        "Conservative",
        {
            "VTI": Decimal("0.15"),
            "VXUS": Decimal("0.05"),
            "BND": Decimal("0.65"),
            "BIL": Decimal("0.15"),
        },
    ),
    _ModelPortfolioSpec(
        "Balanced",
        {
            "VTI": Decimal("0.35"),
            "VXUS": Decimal("0.15"),
            "BND": Decimal("0.45"),
            "BIL": Decimal("0.05"),
        },
    ),
    _ModelPortfolioSpec(
        "Growth",
        {
            "VTI": Decimal("0.55"),
            "VXUS": Decimal("0.20"),
            "BND": Decimal("0.20"),
            "BIL": Decimal("0.05"),
        },
    ),
    _ModelPortfolioSpec(
        "Aggressive",
        {"VTI": Decimal("0.72"), "VXUS": Decimal("0.25"), "BND": Decimal("0.03")},
    ),
)


@dataclass(frozen=True)
class SeedReferenceDataResult:
    securities_created: tuple[str, ...]
    securities_skipped: tuple[str, ...]
    model_portfolios_created: tuple[str, ...]
    model_portfolios_skipped: tuple[str, ...]


def _default_uow() -> RebalanceUnitOfWork:
    return RebalanceUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER)


class SeedReferenceDataJob:
    """Idempotent demo reference-data seed. See module docstring."""

    def __init__(self, *, uow_factory: Callable[[], RebalanceUnitOfWork] = _default_uow) -> None:
        self._uow_factory = uow_factory

    def run(self) -> SeedReferenceDataResult:
        with self._uow_factory() as uow:
            securities_by_symbol, securities_created, securities_skipped = self._seed_securities(
                uow
            )
            model_portfolios_created, model_portfolios_skipped = self._seed_model_portfolios(
                uow, securities_by_symbol
            )
            uow.commit()

        log.info(
            "seed_reference_data.completed",
            securities_created=securities_created,
            securities_skipped=securities_skipped,
            model_portfolios_created=model_portfolios_created,
            model_portfolios_skipped=model_portfolios_skipped,
        )
        return SeedReferenceDataResult(
            securities_created=tuple(securities_created),
            securities_skipped=tuple(securities_skipped),
            model_portfolios_created=tuple(model_portfolios_created),
            model_portfolios_skipped=tuple(model_portfolios_skipped),
        )

    def _seed_securities(
        self, uow: RebalanceUnitOfWork
    ) -> tuple[dict[str, Security], list[str], list[str]]:
        by_symbol: dict[str, Security] = {}
        created: list[str] = []
        skipped: list[str] = []
        for spec in SECURITIES:
            existing = uow.securities.get_by_symbol(spec.symbol)
            if existing is not None:
                by_symbol[spec.symbol] = existing
                skipped.append(spec.symbol)
                continue
            security = Security(symbol=spec.symbol, name=spec.name, asset_class=spec.asset_class)
            uow.securities.add(security)
            by_symbol[spec.symbol] = security
            created.append(spec.symbol)
        # Flush so every new Security has its server/client-generated `id` populated before the
        # target_weight rows below reference it by foreign key, within the same transaction.
        uow.session.flush()
        return by_symbol, created, skipped

    def _seed_model_portfolios(
        self, uow: RebalanceUnitOfWork, securities_by_symbol: dict[str, Security]
    ) -> tuple[list[str], list[str]]:
        created: list[str] = []
        skipped: list[str] = []
        for spec in MODEL_PORTFOLIOS:
            if uow.model_portfolios.get_by_name(spec.name) is not None:
                skipped.append(spec.name)
                continue
            model = ModelPortfolio(name=spec.name)
            uow.model_portfolios.add(model)
            uow.session.flush()
            for symbol, weight_pct in spec.weights.items():
                uow.target_weights.add(
                    TargetWeight(
                        model_portfolio_id=model.id,
                        security_id=securities_by_symbol[symbol].id,
                        weight_pct=weight_pct,
                    )
                )
            created.append(spec.name)
        return created, skipped


__all__ = ["MODEL_PORTFOLIOS", "SECURITIES", "SeedReferenceDataJob", "SeedReferenceDataResult"]
