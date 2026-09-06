"""Orders & custody model aggregates (S3): `order`, `order_event`, `approval_hold`.

The composed `OrdersUnitOfWork` lives in `app/services/orders/uow.py`, not here, since `app/models/`
may not import `app/services/` (S0 §3).
"""

from __future__ import annotations
