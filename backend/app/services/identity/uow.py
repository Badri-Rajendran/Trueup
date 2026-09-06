"""`IdentityUnitOfWork` — adds `.customers`/`.staff`/`.kyc_sessions`/`.bank_links` repositories to
`UnitOfWork` (S0 §5's documented extension mechanism)."""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.identity.bank_link import SqlBankLinkRepository
from app.models.identity.kyc_session import SqlKycSessionRepository
from app.models.identity.repository import (
    BankLinkRepository,
    CustomerRepository,
    KycSessionRepository,
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

    @cached_property
    def kyc_sessions(self) -> KycSessionRepository:
        return SqlKycSessionRepository(self)

    @cached_property
    def bank_links(self) -> BankLinkRepository:
        return SqlBankLinkRepository(self)
