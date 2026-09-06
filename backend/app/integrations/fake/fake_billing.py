"""`FakeBillingAdapter` — the `PaymentPort` fake for `tests/contract/` (S10 §9), no network call.

`build_payment_intent_webhook_body` constructs a real `payment_intent.*` Stripe webhook body (S10 §7).
"""

from __future__ import annotations

import itertools
import uuid
from typing import TYPE_CHECKING, Any

from app.integrations.ports import ChargeHandle, PaymentDeclinedError, PaymentMethodHandle

if TYPE_CHECKING:
    from app.core.money import Money


class FakeBillingAdapter:
    """Implements `PaymentPort` (structural — no inheritance required). `decline_customers` lets a
    test force a specific `stripe_customer_id` to decline every charge (S10 §5/§9)."""

    def __init__(self, *, decline_customers: frozenset[str] = frozenset()) -> None:
        self._counter = itertools.count(1)
        self._decline_customers = decline_customers
        self.attached_methods: list[str] = []
        self.charges: list[tuple[str, Money, str]] = []

    def attach_payment_method(
        self, *, stripe_customer_id: str | None, customer_email: str, payment_method_id: str
    ) -> PaymentMethodHandle:
        customer_id = stripe_customer_id or f"cus_fake_{next(self._counter)}_{uuid.uuid4().hex[:8]}"
        self.attached_methods.append(payment_method_id)
        return PaymentMethodHandle(
            stripe_customer_id=customer_id, stripe_payment_method_id=payment_method_id
        )

    def charge(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        amount: Money,
        idempotency_key: str,
    ) -> ChargeHandle:
        self.charges.append((stripe_customer_id, amount, idempotency_key))
        if stripe_customer_id in self._decline_customers:
            raise PaymentDeclinedError(reason="fake decline for testing")
        charge_id = f"pi_fake_{next(self._counter)}_{uuid.uuid4().hex[:8]}"
        return ChargeHandle(stripe_charge_id=charge_id, status="succeeded")


def build_payment_intent_webhook_body(
    *, stripe_charge_id: str, status: str
) -> dict[str, Any]:
    """A Stripe Billing `payment_intent.*` event body, shaped as `construct_event` would (S10 §7)."""
    return {
        "id": f"evt_fake_{uuid.uuid4().hex[:8]}",
        "type": f"payment_intent.{status}",
        "data": {"object": {"id": stripe_charge_id, "status": status}},
    }


__all__ = ["FakeBillingAdapter", "build_payment_intent_webhook_body"]
