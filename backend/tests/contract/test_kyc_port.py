"""`KycPort` contract (S2 §8): identical assertions against `FakeKycAdapter` and, when configured,
the real `StripeKycAdapter`.
"""

from __future__ import annotations

import os

import pytest

from app.integrations.fake.fake_kyc import FakeKycAdapter
from app.integrations.ports import KycPort


def _assert_valid_handle(port: KycPort) -> None:
    handle = port.create_verification_session(customer_id="00000000-0000-0000-0000-000000000001")
    assert handle.provider_session_id
    assert handle.client_secret


def test_fake_kyc_adapter_satisfies_the_contract() -> None:
    _assert_valid_handle(FakeKycAdapter())


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not os.environ.get("STRIPE_SECRET_KEY"),
    reason="requires a real Stripe Identity sandbox key (STRIPE_SECRET_KEY)",
)
def test_real_stripe_kyc_adapter_satisfies_the_contract() -> None:
    from app.integrations.stripe.kyc_adapter import StripeKycAdapter

    _assert_valid_handle(StripeKycAdapter(api_key=os.environ["STRIPE_SECRET_KEY"]))
