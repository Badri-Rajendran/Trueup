"""A full `DriftEvaluationService` + `RebalanceOrderService` run against a seeded model and
holdings (S9 §9), against real PostgreSQL -- the real `OrderService`/`CashPolicyService`, not
fakes, so this proves the actual DB-backed wiring `MonthlyRebalanceJob` uses end to end.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core.db import DbRole
from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.job_outbox import JobOutbox
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order, OrderSide
from app.models.orders.order_event import OrderEvent
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_service import OrderService
from app.services.rebalance.drift_evaluation_service import (
    DriftEvaluationService,
    NoAssignedModelError,
)
from app.services.rebalance.rebalance_order_service import RebalanceOrderService, real_order_placer
from app.services.rebalance.uow import RebalanceUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_inbound_event

REBALANCE_FLOW_TABLES = [
    *LEDGER_TABLES,
    Security.__table__,
    DailyClose.__table__,
    Order.__table__,
    OrderEvent.__table__,
    ApprovalHold.__table__,
    JobOutbox.__table__,
    ModelPortfolio.__table__,
    TargetWeight.__table__,
    CustomerModelAssignment.__table__,
]

MARKET_DATE = date(2026, 9, 5)
NOW = datetime(2026, 9, 5, 17, 0, tzinfo=UTC)
DRIFT_BAND_PCT = Decimal("0.05")
CASH_BUFFER_PCT = Decimal("0.01")


@pytest.fixture
def rebalance_flow_tables(owner_engine):
    for table in REBALANCE_FLOW_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(REBALANCE_FLOW_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


pytestmark = pytest.mark.usefixtures("rebalance_flow_tables")


def _owner_uow() -> RebalanceUnitOfWork:
    return RebalanceUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _seed_scenario(uow: RebalanceUnitOfWork) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A customer with $50,000 cash, 80 shares of `over_security` (@$100 = $8,000), and no
    holding of `under_security` at all -- assigned to a model targeting 10%/90% of the two,
    so the first is over-weight (a sell) and the second under-weight (a first-time buy)."""
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=KycStatus.approved,
        account_approval_status=AccountApprovalStatus.approved,
    )
    uow.session.add(customer)
    uow.session.flush()
    uow.cash_locks.create_for_customer(customer.id)

    over_security = Security(symbol="OVER", name="Over Co.", asset_class=SecurityAssetClass.EQUITY)
    under_security = Security(
        symbol="UNDER", name="Under Co.", asset_class=SecurityAssetClass.EQUITY
    )
    uow.session.add_all([over_security, under_security])
    uow.session.flush()

    uow.daily_closes.add(
        DailyClose(
            security_id=over_security.id,
            market_date=MARKET_DATE,
            close_price=Price("100.00"),
            source=MarketDataSource.LIVE,
            status=DailyCloseStatus.CONFIRMED,
        )
    )
    uow.daily_closes.add(
        DailyClose(
            security_id=under_security.id,
            market_date=MARKET_DATE,
            close_price=Price("50.00"),
            source=MarketDataSource.LIVE,
            status=DailyCloseStatus.CONFIRMED,
        )
    )

    cash = Account.create(AccountRole.CASH, customer_id=customer.id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer.id)
    units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer.id, security_id=over_security.id
    )
    cost = Account.create(
        AccountRole.POSITION_COST, customer_id=customer.id, security_id=over_security.id
    )
    uow.session.add_all([cash, equity, units, cost])
    uow.session.flush()

    posting = PostingService(uow)
    posting.post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=MARKET_DATE,
        source_event_id=insert_inbound_event(uow.session),
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("50000.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-50000.00")),
        ],
    )
    posting.post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=MARKET_DATE,
        source_event_id=insert_inbound_event(uow.session),
        legs=[
            PostingLeg(account_id=units.id, quantity_units=Units("80")),
            PostingLeg(account_id=cost.id, amount_money=Money("8000.00")),
            PostingLeg(account_id=cash.id, amount_money=Money("-8000.00")),
        ],
    )

    model = ModelPortfolio(name="Aggressive Growth")
    uow.session.add(model)
    uow.session.flush()
    uow.target_weights.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=over_security.id, weight_pct=Decimal("0.10")
        )
    )
    uow.target_weights.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=under_security.id, weight_pct=Decimal("0.90")
        )
    )
    uow.customer_model_assignments.upsert(
        CustomerModelAssignment(
            customer_id=customer.id, model_portfolio_id=model.id, assigned_at=MARKET_DATE
        )
    )
    uow.commit()
    return customer.id, over_security.id, under_security.id


def test_full_run_sells_the_over_weight_holding_and_buys_the_under_weight_one() -> None:
    with _owner_uow() as setup_uow:
        customer_id, over_security_id, under_security_id = _seed_scenario(setup_uow)

    with _owner_uow() as uow:
        evaluation = DriftEvaluationService(uow, drift_band_pct=DRIFT_BAND_PCT).evaluate(
            customer_id, MARKET_DATE
        )
        assert evaluation.completeness == "complete"
        assert evaluation.total_value == Money("50000.00")

        flagged_security_ids = {entry.security_id for entry in evaluation.flagged}
        assert flagged_security_ids == {over_security_id, under_security_id, None}

        cash_policy = CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow))
        order_service = OrderService(
            uow,
            hold_service=ApprovalHoldService(uow),
            cash_policy=cash_policy,
            approval_threshold_usd=Money("1000000.00"),  # well above every order below
            now=lambda: NOW,
        )
        rebalance_orders = RebalanceOrderService(
            order_placer=real_order_placer(order_service),
            cash_provider=cash_policy,
            cash_buffer_pct=CASH_BUFFER_PCT,
        )

        orders = rebalance_orders.generate_orders(evaluation)
        uow.commit()

    assert len(orders) == 2
    by_side = {order.side: order for order in orders}
    assert OrderSide.SELL in by_side
    assert OrderSide.BUY in by_side

    sell_order = by_side[OrderSide.SELL]
    assert sell_order.security_id == over_security_id
    # current $8,000 (16%) vs target $5,000 (10%) of $50,000 -- sell $3,000 worth @ $100.
    assert sell_order.quantity_requested == Units("30")

    buy_order = by_side[OrderSide.BUY]
    assert buy_order.security_id == under_security_id
    assert buy_order.quantity_requested > Units("0")

    with _owner_uow() as uow:
        persisted = uow.orders.list_for_customer(customer_id)
        assert len(persisted) == 2
        holds = [uow.approval_holds.get_by_order_id(order.id) for order in persisted]
        assert all(hold is not None for hold in holds)


def test_evaluate_raises_for_a_customer_with_no_assigned_model() -> None:
    with _owner_uow() as uow:
        customer = Customer(
            email=f"{uuid.uuid4()}@trueup.test",
            password_hash="hash",
            kyc_status=KycStatus.approved,
            account_approval_status=AccountApprovalStatus.approved,
        )
        uow.session.add(customer)
        uow.session.flush()
        uow.commit()

        with pytest.raises(NoAssignedModelError):
            DriftEvaluationService(uow, drift_band_pct=DRIFT_BAND_PCT).evaluate(
                customer.id, MARKET_DATE
            )


def test_evaluate_returns_no_flags_when_everything_is_exactly_on_target() -> None:
    """S9 §8 item 3: the fully-quiescent case -- every holding, including the implicit CASH
    holding, exactly matches its target, so nothing is flagged. `target_weight`'s own sum-to-one
    trigger (S9 §3.2) means a model's named securities always claim the full 100% -- cash's own
    implicit target is therefore always exactly 0 in this schema, never "typically 0"; landing on
    it here means the customer is fully invested with no idle cash left over."""
    with _owner_uow() as uow:
        customer = Customer(
            email=f"{uuid.uuid4()}@trueup.test",
            password_hash="hash",
            kyc_status=KycStatus.approved,
            account_approval_status=AccountApprovalStatus.approved,
        )
        uow.session.add(customer)
        uow.session.flush()

        security = Security(
            symbol="ONTGT", name="On Target Co.", asset_class=SecurityAssetClass.EQUITY
        )
        uow.session.add(security)
        uow.session.flush()
        uow.daily_closes.add(
            DailyClose(
                security_id=security.id,
                market_date=MARKET_DATE,
                close_price=Price("100.00"),
                source=MarketDataSource.LIVE,
                status=DailyCloseStatus.CONFIRMED,
            )
        )

        cash = Account.create(AccountRole.CASH, customer_id=customer.id)
        equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer.id)
        units = Account.create(
            AccountRole.POSITION_UNITS, customer_id=customer.id, security_id=security.id
        )
        cost = Account.create(
            AccountRole.POSITION_COST, customer_id=customer.id, security_id=security.id
        )
        uow.session.add_all([cash, equity, units, cost])
        uow.session.flush()

        posting = PostingService(uow)
        posting.post(
            entry_type=JournalEntryType.DEPOSIT,
            effective_date=MARKET_DATE,
            source_event_id=insert_inbound_event(uow.session),
            legs=[
                PostingLeg(account_id=cash.id, amount_money=Money("10000.00")),
                PostingLeg(account_id=equity.id, amount_money=Money("-10000.00")),
            ],
        )
        # 100 shares @ $100 = $10,000 (100%); $0 cash remains -- both exactly on target.
        posting.post(
            entry_type=JournalEntryType.TRADE_BUY,
            effective_date=MARKET_DATE,
            source_event_id=insert_inbound_event(uow.session),
            legs=[
                PostingLeg(account_id=units.id, quantity_units=Units("100")),
                PostingLeg(account_id=cost.id, amount_money=Money("10000.00")),
                PostingLeg(account_id=cash.id, amount_money=Money("-10000.00")),
            ],
        )

        model = ModelPortfolio(name="Fully Invested")
        uow.session.add(model)
        uow.session.flush()
        uow.target_weights.add(
            TargetWeight(
                model_portfolio_id=model.id, security_id=security.id, weight_pct=Decimal("1.0000")
            )
        )
        uow.customer_model_assignments.upsert(
            CustomerModelAssignment(
                customer_id=customer.id, model_portfolio_id=model.id, assigned_at=MARKET_DATE
            )
        )
        uow.commit()

        evaluation = DriftEvaluationService(uow, drift_band_pct=DRIFT_BAND_PCT).evaluate(
            customer.id, MARKET_DATE
        )
        assert evaluation.completeness == "complete"
        assert evaluation.flagged == ()
