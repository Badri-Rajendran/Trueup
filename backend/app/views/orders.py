"""Response schemas for `app/controllers/api/orders.py` (S3 §6).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, ConfigDict

from app.core.money import (  # noqa: TC001 -- Pydantic resolves field annotations at class-build time.
    Money,
    Price,
    Units,
)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    security_id: uuid.UUID
    symbol: str
    side: str
    quantity_requested: Units
    status: str
    filled_quantity: Units
    average_fill_price: Price | None
    client_order_id: str
    created_at: datetime
    updated_at: datetime


class OrderEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    event_type: str
    execution_id: str | None
    quantity: Units | None
    """Per-fill quantity; only a `fill` event carries one (e.g. `submitted` never does)."""
    price: Price | None
    """Per-fill price; only a `fill` event carries one."""
    recorded_at: datetime


class OpenedLotResponse(BaseModel):
    """A tax lot opened by one of this (buy) order's own fills."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    quantity_opened: Units
    quantity_remaining: Units
    original_cost_basis: Money
    acquired_at: date
    opening_fill_execution_id: str


class ConsumedLotResponse(BaseModel):
    """A lot consumption drawn by one of this (sell) order's own fills."""

    model_config = ConfigDict(from_attributes=True)

    tax_lot_id: uuid.UUID
    quantity_consumed: Units
    realized_gain_loss: Money
    sale_date: date
    closing_fill_execution_id: str


class OrderDetailResponse(BaseModel):
    order: OrderResponse
    events: list[OrderEventResponse]
    opened_lots: list[OpenedLotResponse]
    """Non-empty only for a buy order: the lots its own fills opened."""
    consumed_lots: list[ConsumedLotResponse]
    """Non-empty only for a sell order: the lot consumptions its own fills drew from."""


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]


__all__ = [
    "ConsumedLotResponse",
    "OpenedLotResponse",
    "OrderDetailResponse",
    "OrderEventResponse",
    "OrderListResponse",
    "OrderResponse",
]
