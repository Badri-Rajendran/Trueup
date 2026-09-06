"""`StripeBillingAdapter` (S10 §5/§7, ADR 10) — the only module that calls the Stripe Billing API.

Follows `StripeKycAdapter`'s exact precedent: `services/` depends on `PaymentPort`
(`app/integrations/ports.py`), never this class directly (S0 §3's dependency rule,
`.importlinter`'s `services-use-ports-only` contract).
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
    """Stripe's Payment Intents API takes the smallest currency unit (cents for USD), never a
    decimal dollar amount -- `Money` (`NUMERIC(18,4)`) is deliberately unwrapped only here, at the
    one boundary a provider's own integer-cents contract requires it (ADR 16's same reasoning as
    `order.average_fill_price`), through `Money`'s public `str()` rather than its private
    `Decimal`, so this stays outside `app/core/` without reaching into `Money`'s internals."""
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

        stripe.PaymentMethod.attach(
            payment_method_id, customer=customer_id, api_key=self._api_key
        )
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
            api_key=self._api_key,
        )
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
    """Implements `app.services.intake.event_intake.SignatureVerifier` for Stripe Billing
    webhooks (S0 §6 step 1, ADR 10)."""

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
