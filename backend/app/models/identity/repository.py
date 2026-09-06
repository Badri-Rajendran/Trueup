from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select, tuple_

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
    def search(
        self, query: str, *, limit: int, after: tuple[str, uuid.UUID] | None = None
    ) -> list[Customer]: ...


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

    def search(
        self, query: str, *, limit: int, after: tuple[str, uuid.UUID] | None = None
    ) -> list[Customer]:
        """Case-insensitive email substring match (S8 §4 row 1); keyset-paginated on `(email, id)`."""
        statement = select(Customer).where(Customer.email.ilike(f"%{query}%"))
        if after is not None:
            after_email, after_id = after
            statement = statement.where(
                tuple_(Customer.email, Customer.id) > (after_email, after_id)
            )
        statement = statement.order_by(Customer.email.asc(), Customer.id.asc()).limit(limit + 1)
        return list(self.session.execute(statement).scalars().all())


class SqlStaffRepository(BaseRepository[Staff]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow,
            entity=Staff,
            # `staff` has no RLS policy (S0 §7.2); Staff.id satisfies the required column, unused by tenant scoping.
            customer_id_column=Staff.id,
        )

    def get_by_email(self, email: str) -> Staff | None:
        return self.session.query(Staff).filter_by(email=email).first()

    def get_by_id(self, staff_id: uuid.UUID) -> Staff | None:
        return self.session.query(Staff).filter_by(id=staff_id).first()
