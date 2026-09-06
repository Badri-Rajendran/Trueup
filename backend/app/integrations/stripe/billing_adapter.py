"""`StripeBillingAdapter` (S10 §5/§7, ADR 10) — the only module that calls the Stripe Billing API.
`services/` depends on `PaymentPort`, never this class directly (S0 §3).
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

import stripe

from app.integrations.ports import ChargeHandle, PaymentDeclinedError, PaymentMethodHandle

if TYPE_CHECKING:
    from app.core.money import Money


class StripeCredentialsNotConfiguredError(RuntimeError):
    """Raised rather than silently degrading to a fake when Stripe credentials are absent."""


def _to_cents(amount: Money) -> int:
    """Stripe takes integer cents, never a decimal amount; unwraps `Money` via its public `str()`."""
    cents = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return int(cents)


class StripeBillingAdapter:
    """Implements `PaymentPort` (structural — no inheritance required)."""

    def __init__(self, *, api_key: str) -> None:
        if not api_key:
            raise StripeCredentialsNotConfiguredError(
                "Stripe API key is required to attach a payment method or charge one"
            )
        self._api_key = api_key

    def attach_payment_method(
        self, *, stripe_customer_id: str | None, customer_email: str, payment_method_id: str
    ) -> PaymentMethodHandle:
        customer_id = stripe_customer_id or stripe.Customer.create(
            email=customer_email, api_key=self._api_key
        ).id

        # Stripe's fixed test tokens materialize a new PaymentMethod on `.attach()`; use its own
        # `.id` below, not the caller-supplied one.
        attached = stripe.PaymentMethod.attach(
            payment_method_id, customer=customer_id, api_key=self._api_key
        )
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": attached.id},
            api_key=self._api_key,
        )
        return PaymentMethodHandle(
            stripe_customer_id=customer_id, stripe_payment_method_id=attached.id
        )

    def charge(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        amount: Money,
        idempotency_key: str,
    ) -> ChargeHandle:
        try:
            intent = stripe.PaymentIntent.create(
                amount=_to_cents(amount),
                currency="usd",
                customer=stripe_customer_id,
                payment_method=stripe_payment_method_id,
                off_session=True,
                confirm=True,
                api_key=self._api_key,
                idempotency_key=idempotency_key,
            )
        except stripe.CardError as exc:
            raise PaymentDeclinedError(reason=str(exc.user_message or exc)) from exc
        return ChargeHandle(stripe_charge_id=intent.id, status=intent.status)


class StripeBillingSignatureVerifier:
    """Implements `SignatureVerifier` for Stripe Billing webhooks (S0 §6 step 1, ADR 10)."""

    def __init__(self, *, webhook_secret: str) -> None:
        if not webhook_secret:
            raise StripeCredentialsNotConfiguredError(
                "Stripe Billing webhook secret is required to verify inbound webhooks"
            )
        self._webhook_secret = webhook_secret

    def verify(self, *, payload: bytes, signature: str | None) -> bool:
        if signature is None:
            return False
        try:
            stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except (stripe.SignatureVerificationError, ValueError):
            return False
        return True
