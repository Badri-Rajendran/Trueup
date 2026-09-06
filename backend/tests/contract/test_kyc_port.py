"""`KycPort` contract (S2 §8): identical assertions against `FakeKycAdapter` and, when configured,
the real `StripeKycAdapter`.
"""

from __future__ import annotations

import os

import pytest

from app.integrations.fake.fake_kyc import FakeKycAdapter
from app.integrations.ports import KycPort


def _assert_valid_handle(port: KycPort) -> str:
    handle = port.create_verification_session(customer_id="00000000-0000-0000-0000-000000000001")
    assert handle.provider_session_id
    assert handle.client_secret
    return handle.provider_session_id


def _assert_retrieves_a_status(port: KycPort, provider_session_id: str) -> None:
    status = port.retrieve_verification_session(provider_session_id=provider_session_id)
    assert isinstance(status, str)
    assert status


def test_fake_kyc_adapter_satisfies_the_contract() -> None:
    provider_session_id = _assert_valid_handle(FakeKycAdapter())
    _assert_retrieves_a_status(FakeKycAdapter(), provider_session_id)


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not os.environ.get("STRIPE_SECRET_KEY"),
    reason="requires a real Stripe Identity sandbox key (STRIPE_SECRET_KEY)",
)
def test_real_stripe_kyc_adapter_satisfies_the_contract() -> None:
    from app.integrations.stripe.kyc_adapter import StripeKycAdapter

    adapter = StripeKycAdapter(api_key=os.environ["STRIPE_SECRET_KEY"])
    provider_session_id = _assert_valid_handle(adapter)
    _assert_retrieves_a_status(adapter, provider_session_id)
