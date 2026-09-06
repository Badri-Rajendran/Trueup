"""`PaymentPort` contract (S10 §9): identical assertions against `FakeBillingAdapter` and, when
configured, the real `StripeBillingAdapter`.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.core.money import Money
from app.integrations.fake.fake_billing import FakeBillingAdapter
from app.integrations.ports import PaymentDeclinedError, PaymentPort


def _assert_attach_and_charge_succeed(port: PaymentPort, *, customer_email: str) -> None:
    method = port.attach_payment_method(
        stripe_customer_id=None,
        customer_email=customer_email,
        payment_method_id="pm_card_visa",
    )
    assert method.stripe_customer_id
    # Not asserted equal to the input: the real adapter legitimately returns a different id.
    assert method.stripe_payment_method_id

    handle = port.charge(
        stripe_customer_id=method.stripe_customer_id,
        stripe_payment_method_id=method.stripe_payment_method_id,
        amount=Money("12.34"),
        idempotency_key=str(uuid.uuid4()),
    )
    assert handle.stripe_charge_id
    assert handle.status == "succeeded"


def test_fake_billing_adapter_satisfies_the_contract() -> None:
    _assert_attach_and_charge_succeed(
        FakeBillingAdapter(), customer_email=f"{uuid.uuid4()}@trueup.test"
    )


def test_fake_billing_adapter_raises_payment_declined_for_a_declined_customer() -> None:
    port = FakeBillingAdapter()
    method = port.attach_payment_method(
        stripe_customer_id=None,
        customer_email=f"{uuid.uuid4()}@trueup.test",
        payment_method_id="pm_card_chargeDeclined",
    )
    port = FakeBillingAdapter(decline_customers=frozenset({method.stripe_customer_id}))
    with pytest.raises(PaymentDeclinedError):
        port.charge(
            stripe_customer_id=method.stripe_customer_id,
            stripe_payment_method_id=method.stripe_payment_method_id,
            amount=Money("5.00"),
            idempotency_key=str(uuid.uuid4()),
        )


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not os.environ.get("STRIPE_SECRET_KEY"),
    reason="requires a real Stripe Billing sandbox key (STRIPE_SECRET_KEY)",
)
def test_real_stripe_billing_adapter_satisfies_the_contract() -> None:
    from app.integrations.stripe.billing_adapter import StripeBillingAdapter

    _assert_attach_and_charge_succeed(
        StripeBillingAdapter(api_key=os.environ["STRIPE_SECRET_KEY"]),
        customer_email=f"{uuid.uuid4()}@trueup.test",
    )
