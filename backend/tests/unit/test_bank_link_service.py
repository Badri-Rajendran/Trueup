"""`BankLinkService` (S2 §3.3/§5.1/§5.4) — pure unit tests against real fakes, no database."""

from __future__ import annotations

import uuid

import pytest

from app.integrations.fake.fake_bank import FakeBankAdapter
from app.models.identity.bank_link import BankLink, BankLinkStatus
from app.services.identity.bank_link_service import BankLinkNotFoundError, BankLinkService


class _FakeBankLinks:
    def __init__(self) -> None:
        self.rows: list[BankLink] = []

    def add(self, link: BankLink) -> None:
        self.rows.append(link)

    def get_by_plaid_item_id(self, plaid_item_id: str) -> BankLink | None:
        return next((r for r in self.rows if r.plaid_item_id == plaid_item_id), None)

    def active_for_customer(self, customer_id: uuid.UUID) -> BankLink | None:
        return next(
            (
                r
                for r in self.rows
                if r.customer_id == customer_id and r.status is BankLinkStatus.ACTIVE
            ),
            None,
        )

    def current_for_customer(self, customer_id: uuid.UUID) -> BankLink | None:
        return next(
            (
                r
                for r in self.rows
                if r.customer_id == customer_id
                and r.status in (BankLinkStatus.ACTIVE, BankLinkStatus.REQUIRES_REAUTH)
            ),
            None,
        )

    def supersede_and_activate(self, new_link: BankLink) -> None:
        for row in self.rows:
            if row.customer_id == new_link.customer_id and row.status in (
                BankLinkStatus.ACTIVE,
                BankLinkStatus.REQUIRES_REAUTH,
            ):
                row.status = BankLinkStatus.SUPERSEDED
        self.add(new_link)


class _FakeUow:
    def __init__(self) -> None:
        self.bank_links = _FakeBankLinks()


def test_create_link_activates_a_new_link() -> None:
    uow = _FakeUow()
    service = BankLinkService(uow, bank_port=FakeBankAdapter())  # type: ignore[arg-type]
    customer_id = uuid.uuid4()

    link = service.create_link(customer_id, plaid_public_token="public-fake-token")

    assert link.status is BankLinkStatus.ACTIVE
    assert uow.bank_links.active_for_customer(customer_id) is link


def test_relinking_supersedes_the_prior_active_link() -> None:
    uow = _FakeUow()
    service = BankLinkService(uow, bank_port=FakeBankAdapter())  # type: ignore[arg-type]
    customer_id = uuid.uuid4()

    first = service.create_link(customer_id, plaid_public_token="public-fake-token-1")
    second = service.create_link(customer_id, plaid_public_token="public-fake-token-2")

    assert first.status is BankLinkStatus.SUPERSEDED
    assert second.status is BankLinkStatus.ACTIVE
    assert uow.bank_links.active_for_customer(customer_id) is second


def test_item_login_required_transitions_an_active_link_to_requires_reauth() -> None:
    uow = _FakeUow()
    service = BankLinkService(uow, bank_port=FakeBankAdapter())  # type: ignore[arg-type]
    link = service.create_link(uuid.uuid4(), plaid_public_token="public-fake-token")

    service.apply_item_login_required(link.plaid_item_id)

    assert link.status is BankLinkStatus.REQUIRES_REAUTH


def test_item_login_required_on_a_superseded_link_is_ignored() -> None:
    uow = _FakeUow()
    service = BankLinkService(uow, bank_port=FakeBankAdapter())  # type: ignore[arg-type]
    customer_id = uuid.uuid4()
    old = service.create_link(customer_id, plaid_public_token="public-fake-token-1")
    service.create_link(customer_id, plaid_public_token="public-fake-token-2")

    service.apply_item_login_required(old.plaid_item_id)

    assert old.status is BankLinkStatus.SUPERSEDED


def test_item_login_required_for_an_unknown_item_raises() -> None:
    uow = _FakeUow()
    service = BankLinkService(uow, bank_port=FakeBankAdapter())  # type: ignore[arg-type]

    with pytest.raises(BankLinkNotFoundError):
        service.apply_item_login_required("item-unknown")
