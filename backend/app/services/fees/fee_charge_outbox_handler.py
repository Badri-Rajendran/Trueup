"""Outbox task handler for `"charge_fee"` (S10 §5, ADR 10). Stripe call runs with no DB transaction open."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.integrations.ports import PaymentDeclinedError
from app.models.fees.fee_charge import FeeChargeStatus
from app.services.fees.fee_charge_service import FeeChargeNotFoundError, FeeChargeService

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from app.integrations.ports import PaymentPort
    from app.services.fees.uow import FeesUnitOfWork


class NoPaymentMethodError(RuntimeError):
    """No `payment_method` attached; propagates so the outbox retries later."""


class UnregisteredFeeOutboxTaskError(RuntimeError):
    pass


class FeeChargeOutboxHandler:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], FeesUnitOfWork],
        payment_port: PaymentPort,
        dunning_max_attempts: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._payment_port = payment_port
        self._dunning_max_attempts = dunning_max_attempts
        self._now = now

    def handle(self, *, task: str, payload: dict[str, Any]) -> None:
        """Matches `OutboxTaskHandler`'s shape (`app/workers/outbox.py`)."""
        if task != "charge_fee":
            raise UnregisteredFeeOutboxTaskError(f"no fee outbox route for task {task!r}")
        self.charge_fee(uuid.UUID(payload["fee_charge_id"]))

    def charge_fee(self, fee_charge_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            charge = uow.fee_charges.get_by_id(fee_charge_id)
            if charge is None:
                uow.commit()
                raise FeeChargeNotFoundError(f"no fee_charge {fee_charge_id}")
            if charge.status not in (FeeChargeStatus.PENDING, FeeChargeStatus.FAILED):
                uow.commit()
                return  # already succeeded, or exhausted and no longer auto-retried

            method = uow.payment_methods.get_by_customer(charge.customer_id)
            if method is None:
                uow.commit()
                raise NoPaymentMethodError(f"customer {charge.customer_id} has no payment_method")

            stripe_customer_id = method.stripe_customer_id
            stripe_payment_method_id = method.stripe_payment_method_id
            amount = charge.total_accrued
            uow.commit()

        try:
            handle = self._payment_port.charge(
                stripe_customer_id=stripe_customer_id,
                stripe_payment_method_id=stripe_payment_method_id,
                amount=amount,
                idempotency_key=str(fee_charge_id),
            )
        except PaymentDeclinedError:
            with self._uow_factory() as uow:
                FeeChargeService(
                    uow, dunning_max_attempts=self._dunning_max_attempts, now=self._now
                ).apply_charge_failure(fee_charge_id)
                uow.commit()
            return

        with self._uow_factory() as uow:
            FeeChargeService(
                uow, dunning_max_attempts=self._dunning_max_attempts, now=self._now
            ).apply_charge_success(fee_charge_id, stripe_charge_id=handle.stripe_charge_id)
            uow.commit()


__all__ = ["FeeChargeOutboxHandler", "NoPaymentMethodError", "UnregisteredFeeOutboxTaskError"]
