from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.core.repository import BaseRepository
from app.models.identity.customer import Customer
from app.models.identity.staff import Staff

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from app.core.uow import UnitOfWork
    from app.models.identity.bank_link import BankLink
    from app.models.identity.kyc_session import KycSession, KycSessionStatus


class CustomerRepository(Protocol):
    def get_by_email(self, email: str) -> Customer | None: ...
    def get_by_id(self, customer_id: uuid.UUID) -> Customer | None: ...
    def add(self, customer: Customer) -> None: ...


class StaffRepository(Protocol):
    def get_by_email(self, email: str) -> Staff | None: ...
    def get_by_id(self, staff_id: uuid.UUID) -> Staff | None: ...
    def add(self, staff: Staff) -> None: ...


class KycSessionRepository(Protocol):
    def get_by_provider_session_id(self, provider_session_id: str) -> KycSession | None: ...
    def get_by_id(self, kyc_session_id: uuid.UUID) -> KycSession | None: ...
    def latest_for_customer(self, customer_id: uuid.UUID) -> KycSession | None: ...
    def resolve(
        self, session_row: KycSession, *, status: KycSessionStatus, resolved_at: datetime
    ) -> None: ...
    def add(self, session_row: KycSession) -> None: ...


class BankLinkRepository(Protocol):
    def get_by_id(self, bank_link_id: uuid.UUID) -> BankLink | None: ...
    def get_by_plaid_item_id(self, plaid_item_id: str) -> BankLink | None: ...
    def active_for_customer(self, customer_id: uuid.UUID) -> BankLink | None: ...
    def current_for_customer(self, customer_id: uuid.UUID) -> BankLink | None: ...
    def supersede_and_activate(self, new_link: BankLink) -> None: ...


class SqlCustomerRepository(BaseRepository[Customer]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=Customer, customer_id_column=Customer.id)

    def get_by_email(self, email: str) -> Customer | None:
        return self.session.query(Customer).filter_by(email=email).first()

    def get_by_id(self, customer_id: uuid.UUID) -> Customer | None:
        return self.session.query(Customer).filter_by(id=customer_id).first()


class SqlStaffRepository(BaseRepository[Staff]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow,
            entity=Staff,
            # `staff` carries no `customer_id` and has no RLS policy (S0 §7.2: it isn't a
            # customer-scoped table) — `Staff.id` satisfies `BaseRepository`'s required column
            # without being used by any tenant-scoped query (`get_by_email`/`get_by_id` below
            # bypass `_tenant_scoped()` entirely, by design: a login lookup must scan every row).
            customer_id_column=Staff.id,
        )

    def get_by_email(self, email: str) -> Staff | None:
        return self.session.query(Staff).filter_by(email=email).first()

    def get_by_id(self, staff_id: uuid.UUID) -> Staff | None:
        return self.session.query(Staff).filter_by(id=staff_id).first()
