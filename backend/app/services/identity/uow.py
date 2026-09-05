"""`IdentityUnitOfWork` — adds `.customers`/`.staff` repositories to `UnitOfWork` (S0 §5's
documented extension mechanism)."""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.identity.repository import (
    CustomerRepository,
    SqlCustomerRepository,
    SqlStaffRepository,
    StaffRepository,
)


class IdentityUnitOfWork(UnitOfWork):
    @cached_property
    def customers(self) -> CustomerRepository:
        return SqlCustomerRepository(self)

    @cached_property
    def staff(self) -> StaffRepository:
        return SqlStaffRepository(self)
