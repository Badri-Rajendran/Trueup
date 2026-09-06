"""Orders & custody model aggregates (S3): `order`, `order_event`, `approval_hold`.

The composed `UnitOfWork` combining these repositories with identity/ledger/ops (`OrdersUnitOfWork`)
lives in `app/services/orders/uow.py`, not here -- it depends on `IdentityUnitOfWork`
(`app/services/identity/uow.py`, services layer), and `app/models/` may not import `app/services/`
(S0 §3, enforced by `lint-imports`). `FundingUnitOfWork` (S2) is the identical precedent: also a
composed `UnitOfWork` living in `app/services/` for the same reason.
"""

from __future__ import annotations
