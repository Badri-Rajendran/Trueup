"""Response schemas for `app/controllers/api/orders.py` (S3 §6).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import datetime  # noqa: TC003

from pydantic import BaseModel, ConfigDict

from app.core.money import (  # noqa: TC001 -- Pydantic resolves field annotations at class-build time.
    Price,
    Units,
)


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    security_id: uuid.UUID
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
    recorded_at: datetime


class OrderDetailResponse(BaseModel):
    order: OrderResponse
    events: list[OrderEventResponse]


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]


__all__ = [
    "OrderDetailResponse",
    "OrderEventResponse",
    "OrderListResponse",
    "OrderResponse",
]
