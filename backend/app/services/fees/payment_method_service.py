"""Attaches/updates the customer's Stripe-linked payment method (S10 §7). Never handles raw card data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.fees.payment_method import PaymentMethod

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from app.integrations.ports import PaymentPort
    from app.services.fees.uow import FeesUnitOfWork


class CustomerNotFoundError(RuntimeError):
    pass


class PaymentMethodService:
    def __init__(
        self,
        uow: FeesUnitOfWork,
        *,
        payment_port: PaymentPort,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._payment_port = payment_port
        self._now = now

    def attach(self, customer_id: uuid.UUID, *, payment_method_id: str) -> PaymentMethod:
        customer = self._uow.customers.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"no customer {customer_id}")

        existing = self._uow.payment_methods.get_by_customer(customer_id)
        handle = self._payment_port.attach_payment_method(
            stripe_customer_id=existing.stripe_customer_id if existing is not None else None,
            customer_email=customer.email,
            payment_method_id=payment_method_id,
        )
        return self._uow.payment_methods.upsert(
            PaymentMethod(
                customer_id=customer_id,
                stripe_customer_id=handle.stripe_customer_id,
                stripe_payment_method_id=handle.stripe_payment_method_id,
                updated_at=self._now(),
            )
        )


__all__ = ["CustomerNotFoundError", "PaymentMethodService"]
