"""`LotConsumptionService` (S5 §4, ADR 4) -- against real Postgres, since both `record_buy_fill`/
`record_sell_fill` open/consume lots and post to the ledger in the same transaction.

S5 §8's own testing strategy names two required cases neither had a dedicated test for before
this file (36% incidental coverage, from one assertion inside an unrelated trade-update-handler
test): "FIFO ordering property test (oldest lot always consumed first absent an override)" and
"the quantity_remaining >= 0 CHECK constraint actually rejects an over-consumption attempt at the
database level, not just in application logic." Found during a full spec/security/quality audit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.clock import InMemoryTradingCalendar, MarketClock
from app.core.db import DbRole
from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.models.identity.customer import Customer
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.daily_close import DailyClose
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.models.restatement.restatement_event import RestatementEvent
from app.services.lots.lot_consumption_service import (
    InsufficientLotsError,
    LotConsumptionService,
    UnknownTaxLotError,
)
from app.services.lots.uow import LotsUnitOfWork
from tests.integration.conftest import LEDGER_TABLES

LOT_CONSUMPTION_TABLES = [
    *LEDGER_TABLES,
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ValuationRun.__table__,
    SubPeriodReturn.__table__,
    PublishedSnapshot.__table__,
    RestatementEvent.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
]

# All weekdays -- InMemoryTradingCalendar treats every weekday as a trading day, no seeding needed.
DAY_1 = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
DAY_2 = datetime(2026, 1, 6, 16, 0, tzinfo=UTC)
DAY_3 = datetime(2026, 1, 7, 16, 0, tzinfo=UTC)
DAY_4 = datetime(2026, 1, 8, 16, 0, tzinfo=UTC)
# A distinct weekday per lot for the FIFO property test below (up to 4 lots), all strictly
# before the sell on the following Monday.
BUY_DAYS = [
    datetime(2026, 1, 5, 16, 0, tzinfo=UTC),
    datetime(2026, 1, 6, 16, 0, tzinfo=UTC),
    datetime(2026, 1, 7, 16, 0, tzinfo=UTC),
    datetime(2026, 1, 8, 16, 0, tzinfo=UTC),
]
SELL_DAY = datetime(2026, 1, 12, 16, 0, tzinfo=UTC)


@pytest.fixture
def lot_consumption_tables(owner_engine):
    for table in LOT_CONSUMPTION_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(LOT_CONSUMPTION_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("lot_consumption_tables")


def _owner_uow() -> LotsUnitOfWork:
    return LotsUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _market_clock() -> MarketClock:
    return MarketClock(InMemoryTradingCalendar())


def _insert_customer_with_cash(uow: LotsUnitOfWork) -> uuid.UUID:
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    uow.session.add(customer)
    uow.session.flush()
    uow.session.add(CustomerCashLock(customer_id=customer.id))
    uow.session.add(Account.create(AccountRole.CASH, customer_id=customer.id))
    uow.session.flush()
    return customer.id


def _insert_security(uow: LotsUnitOfWork) -> uuid.UUID:
    # A fresh symbol per call, not a fixed "AAPL": the Hypothesis-driven test below invokes this
    # helper multiple times within one test function run (each `@given` example commits for
    # real, rather than rolling back), so a fixed symbol would collide on `uq_security_symbol`
    # from the second example onward.
    security = Security(
        symbol=f"TST{uuid.uuid4().hex[:8]}", name="Test Co", asset_class=SecurityAssetClass.EQUITY
    )
    uow.session.add(security)
    uow.session.flush()
    return security.id


def _service(uow: LotsUnitOfWork) -> LotConsumptionService:
    return LotConsumptionService(uow, market_clock=_market_clock())


def _record_fill_order_event(
    uow: LotsUnitOfWork, *, customer_id: uuid.UUID, security_id: uuid.UUID,
    execution_id: str, quantity: Units,
) -> None:
    """`TaxLot.opening_fill_execution_id` FKs to `order_event.execution_id` -- in production
    `AlpacaTradeUpdateHandler` creates this row before calling `record_buy_fill`; standing in for
    that caller here."""
    order = Order(
        customer_id=customer_id, security_id=security_id, side=OrderSide.BUY,
        quantity_requested=quantity, status=OrderStatus.FILLED, filled_quantity=quantity,
        client_order_id=derive_client_order_id(uuid.uuid4()),
    )
    uow.session.add(order)
    uow.session.flush()
    uow.session.add(
        OrderEvent(
            order_id=order.id, seq=1, event_type=OrderEventType.FILL,
            execution_id=execution_id, payload={},
        )
    )
    uow.session.flush()


def _buy(
    service: LotConsumptionService, uow: LotsUnitOfWork, *,
    customer_id: uuid.UUID, security_id: uuid.UUID, execution_id: str,
    quantity: Units, price: Price, filled_at: datetime,
) -> TaxLot:
    _record_fill_order_event(
        uow, customer_id=customer_id, security_id=security_id,
        execution_id=execution_id, quantity=quantity,
    )
    return service.record_buy_fill(
        customer_id=customer_id, security_id=security_id, execution_id=execution_id,
        quantity=quantity, price=price, filled_at=filled_at,
    )


def _sell(
    service: LotConsumptionService, uow: LotsUnitOfWork, *,
    customer_id: uuid.UUID, security_id: uuid.UUID, execution_id: str,
    quantity: Units, price: Price, filled_at: datetime,
    designated_lot_ids: list[uuid.UUID] | None = None,
) -> list[LotConsumption]:
    """`LotConsumption.closing_fill_execution_id` FKs to `order_event.execution_id` too --
    the same real-caller stand-in as `_buy`."""
    _record_fill_order_event(
        uow, customer_id=customer_id, security_id=security_id,
        execution_id=execution_id, quantity=quantity,
    )
    return service.record_sell_fill(
        customer_id=customer_id, security_id=security_id, execution_id=execution_id,
        quantity=quantity, price=price, filled_at=filled_at,
        designated_lot_ids=designated_lot_ids,
    )


# --- record_buy_fill ------------------------------------------------------------------------


def test_record_buy_fill_opens_a_lot_and_posts_the_trade_buy_entry() -> None:
    from app.models.ledger.posting import Posting

    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        lot = _buy(
            service, uow, customer_id=customer_id, security_id=security_id,
            execution_id="exec-1", quantity=Units("10"), price=Price("100.00"), filled_at=DAY_1,
        )
        uow.commit()

        assert lot.quantity_opened == Units("10")
        assert lot.quantity_remaining == Units("10")
        assert lot.original_cost_basis == Money("1000.00")
        assert lot.adjusted_basis == Money("1000.00")

        legs = uow.session.query(Posting).all()
        cash_legs = [leg for leg in legs if leg.amount_money == Money("-1000.00")]
        assert len(cash_legs) == 1  # the cash outflow leg


# --- record_sell_fill: FIFO default (ADR 4) -----------------------------------------------


def test_record_sell_fill_consumes_the_oldest_lot_first() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        older = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-older",
            quantity=Units("10"), price=Price("100.00"), filled_at=DAY_1,
        )
        newer = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-newer",
            quantity=Units("10"), price=Price("200.00"), filled_at=DAY_2,
        )

        consumptions = _sell(
            service, uow, customer_id=customer_id, security_id=security_id,
            execution_id="exec-sell", quantity=Units("5"), price=Price("150.00"), filled_at=DAY_3,
        )
        uow.commit()

        assert len(consumptions) == 1
        assert consumptions[0].tax_lot_id == older.id  # oldest consumed first, never the newer

        uow.session.refresh(older)
        uow.session.refresh(newer)
        assert older.quantity_remaining == Units("5")
        assert newer.quantity_remaining == Units("10")  # untouched


def test_record_sell_fill_spans_multiple_lots_in_fifo_order() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        older = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-older",
            quantity=Units("5"), price=Price("100.00"), filled_at=DAY_1,
        )
        newer = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-newer",
            quantity=Units("10"), price=Price("200.00"), filled_at=DAY_2,
        )

        # Sells 8: exhausts the older 5-unit lot entirely, then draws 3 from the newer lot.
        consumptions = _sell(
            service, uow, customer_id=customer_id, security_id=security_id,
            execution_id="exec-sell", quantity=Units("8"), price=Price("150.00"), filled_at=DAY_3,
        )
        uow.commit()

        assert len(consumptions) == 2
        by_lot = {c.tax_lot_id: c.quantity_consumed for c in consumptions}
        assert by_lot[older.id] == Units("5")
        assert by_lot[newer.id] == Units("3")

        uow.session.refresh(older)
        uow.session.refresh(newer)
        assert older.quantity_remaining == Units("0")
        assert newer.quantity_remaining == Units("7")


@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    lot_quantities=st.lists(
        st.integers(min_value=1, max_value=20), min_size=2, max_size=4
    ),
    sell_fraction=st.integers(min_value=1, max_value=99),
)
def test_fifo_always_consumes_lots_in_acquisition_order(
    lot_quantities: list[int], sell_fraction: int
) -> None:
    """S5 §8's literal requirement: "oldest lot always consumed first absent an override" --
    property-checked over an arbitrary number of lots and an arbitrary partial sell size, not
    just the two fixed-shape examples above."""
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        lots_oldest_first = []
        for i, quantity in enumerate(lot_quantities):
            lot = _buy(
                service, uow,
                customer_id=customer_id, security_id=security_id,
                execution_id=f"exec-{uuid.uuid4()}-{i}",
                # A distinct acquisition day per lot -- lock_open_fifo orders by
                # (acquired_at, id), so lots sharing one date would make "oldest first" ambiguous
                # (id is random), not a property of FIFO ordering itself.
                quantity=Units(str(quantity)), price=Price("10.00"), filled_at=BUY_DAYS[i],
            )
            lots_oldest_first.append(lot)
        uow.session.flush()

        total_units = sum(lot_quantities)
        sell_quantity = max(1, (total_units * sell_fraction) // 100)
        # Never try to sell more than exists across all lots.
        sell_quantity = min(sell_quantity, total_units)

        consumptions = _sell(
            service, uow, customer_id=customer_id, security_id=security_id,
            execution_id=f"exec-sell-{uuid.uuid4()}", quantity=Units(str(sell_quantity)),
            price=Price("10.00"), filled_at=SELL_DAY,
        )
        uow.commit()

        # The sequence of lots actually touched, in the order fold() consumed them, must be a
        # prefix of the acquisition order -- never a newer lot touched before an older one with
        # remaining quantity.
        touched_lot_ids = [c.tax_lot_id for c in consumptions]
        expected_prefix = [lot.id for lot in lots_oldest_first][: len(touched_lot_ids)]
        assert touched_lot_ids == expected_prefix


# --- record_sell_fill: specific-ID override (ADR 4) -----------------------------------------


def test_record_sell_fill_honours_a_specific_lot_designation_over_fifo_order() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        older = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-older",
            quantity=Units("10"), price=Price("100.00"), filled_at=DAY_1,
        )
        newer = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-newer",
            quantity=Units("10"), price=Price("50.00"), filled_at=DAY_2,
        )

        # Explicitly designates the *newer* (otherwise-second) lot -- FIFO would pick `older`.
        consumptions = _sell(
            service, uow, customer_id=customer_id, security_id=security_id,
            execution_id="exec-sell", quantity=Units("5"), price=Price("150.00"), filled_at=DAY_3,
            designated_lot_ids=[newer.id],
        )
        uow.commit()

        assert len(consumptions) == 1
        assert consumptions[0].tax_lot_id == newer.id

        uow.session.refresh(older)
        uow.session.refresh(newer)
        assert older.quantity_remaining == Units("10")  # untouched
        assert newer.quantity_remaining == Units("5")

        uow.session.refresh(newer)
        from app.models.ledger.tax_lot import LotDesignation

        assert newer.designation is LotDesignation.SPECIFIC


def test_record_sell_fill_rejects_a_designated_lot_belonging_to_another_customer() -> None:
    with _owner_uow() as uow:
        customer_a = _insert_customer_with_cash(uow)
        customer_b = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        others_lot = _buy(
            service, uow,
            customer_id=customer_b, security_id=security_id, execution_id="exec-b",
            quantity=Units("10"), price=Price("100.00"), filled_at=DAY_1,
        )

        with pytest.raises(UnknownTaxLotError):
            service.record_sell_fill(
                customer_id=customer_a, security_id=security_id, execution_id="exec-sell",
                quantity=Units("5"), price=Price("150.00"), filled_at=DAY_2,
                designated_lot_ids=[others_lot.id],
            )


def test_record_sell_fill_rejects_a_nonexistent_designated_lot_id() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        with pytest.raises(UnknownTaxLotError):
            service.record_sell_fill(
                customer_id=customer_id, security_id=security_id, execution_id="exec-sell",
                quantity=Units("5"), price=Price("150.00"), filled_at=DAY_2,
                designated_lot_ids=[uuid.uuid4()],
            )


# --- record_sell_fill: over-consumption (S5 §7 edge case 6) ---------------------------------


def test_record_sell_fill_raises_when_quantity_exceeds_every_open_lot() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-1",
            quantity=Units("5"), price=Price("100.00"), filled_at=DAY_1,
        )

        with pytest.raises(InsufficientLotsError):
            service.record_sell_fill(
                customer_id=customer_id, security_id=security_id, execution_id="exec-sell",
                quantity=Units("10"), price=Price("150.00"), filled_at=DAY_2,
            )


def test_quantity_remaining_check_constraint_rejects_a_negative_value_at_the_db_level() -> None:
    """S5 §8's integration-level requirement: the CHECK itself, independent of
    InsufficientLotsError -- a direct write that bypasses the service entirely must still fail."""
    with _owner_uow() as uow:
        customer_id = _insert_customer_with_cash(uow)
        security_id = _insert_security(uow)
        service = _service(uow)

        lot = _buy(
            service, uow,
            customer_id=customer_id, security_id=security_id, execution_id="exec-1",
            quantity=Units("5"), price=Price("100.00"), filled_at=DAY_1,
        )
        uow.commit()

    with _owner_uow() as uow:
        db_lot = uow.session.get(TaxLot, lot.id)
        db_lot.quantity_remaining = Units("-1")
        with pytest.raises((IntegrityError, DBAPIError)):
            uow.commit()
