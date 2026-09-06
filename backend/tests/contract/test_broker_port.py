"""`BrokerPort` contract (S3 §8): identical assertions against `FakeBrokerAdapter` and, when
configured, the real `AlpacaBrokerAdapter`.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.integrations.fake.fake_broker import FakeBrokerAdapter
from app.integrations.ports import BrokerPort, OrderSide


def _assert_valid_handle(port: BrokerPort) -> None:
    client_order_id = f"trueup-{uuid.uuid4()}"
    handle = port.submit_order(
        client_order_id=client_order_id,
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity="1.5",
    )
    assert handle.client_order_id == client_order_id
    assert handle.broker_order_id


def test_fake_broker_adapter_satisfies_the_contract() -> None:
    _assert_valid_handle(FakeBrokerAdapter())


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY")),
    reason="requires real Alpaca paper-trading credentials",
)
def test_real_alpaca_broker_adapter_satisfies_the_contract() -> None:
    from app.integrations.alpaca.broker_adapter import AlpacaBrokerAdapter

    _assert_valid_handle(
        AlpacaBrokerAdapter(
            api_key_id=os.environ["ALPACA_API_KEY_ID"],
            api_secret_key=os.environ["ALPACA_API_SECRET_KEY"],
            paper=True,
        )
    )
