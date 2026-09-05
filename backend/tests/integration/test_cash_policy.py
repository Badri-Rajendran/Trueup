"""S1 §7 item 5 -- `CashPolicyService`'s `withdrawable`/`investable` (§5, ADR 5).

Table-driven over the scenarios §7 names explicitly: no obligations, one pending sell, one
pending deposit (investable but not withdrawable -- ADR 5's asymmetry), one failed deposit
(FR-6), and a free-riding-shaped scenario (bought with unsettled proceeds, then sold before they
settle) -- proving the *policy functions* compose correctly under that shape. §5.1's free-riding
*guard* itself joins through lot consumption, which is S5's to build (§5.1: "noted here as an S5
dependency, not built in S1") -- this test does not assert a flag that does not exist yet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from app.core.money import Money
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ledger.settlement_obligation import (
    SettlementObligation,
    SettlementObligationRepository,
    SettlementObligationStatus,
)
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.ledger.posting_service import PostingLeg, PostingService
from tests.integration.conftest import insert_customer, insert_inbound_event

pytestmark = pytest.mark.usefixtures("ledger_tables")


class _LedgerLikeUow:
    def __init__(self, session):
        self.session = session

        class _Repo:
            def __init__(self, session):
                self._session = session

            def add(self, obj):
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


class _FakeHoldsProvider:
    """S3 hasn't been built yet -- a configurable fake standing in for its contract."""

    def __init__(
        self,
        *,
        holds: Money | None = None,
        open_buy_commitments: Money | None = None,
    ) -> None:
        self._holds = holds if holds is not None else Money("0.00")
        self._open_buy_commitments = (
            open_buy_commitments if open_buy_commitments is not None else Money("0.00")
        )

    def holds(self, customer_id: uuid.UUID) -> Money:
        return self._holds

    def open_buy_commitments(self, customer_id: uuid.UUID) -> Money:
        return self._open_buy_commitments


def _accounts(session, customer_id) -> dict[str, Account]:
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
    }
    session.add_all(accounts.values())
    session.flush()
    return accounts


def _post_deposit(session, accounts, *, amount: Money) -> uuid.UUID:
    """A settled deposit with no settlement_obligation at all (§5: "no obligation required")."""
    event_id = insert_inbound_event(session)
    entry = PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=accounts["cash"].id, amount_money=amount),
            PostingLeg(account_id=accounts["customer_equity"].id, amount_money=-amount),
        ],
    )
    return entry.id


def _post_with_obligation(
    session,
    accounts,
    *,
    entry_type: JournalEntryType,
    amount: Money,
    status: SettlementObligationStatus,
) -> SettlementObligation:
    """Posts the economic entry and a settlement_obligation tracking whether it has settled,
    matching S1 §4's "not every entry needs one; every entry moving cash against an external
    counterparty does" (a deposit or a sell, here)."""
    event_id = insert_inbound_event(session)
    entry = PostingService(_LedgerLikeUow(session)).post(
        entry_type=entry_type,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=accounts["cash"].id, amount_money=amount),
            PostingLeg(account_id=accounts["customer_equity"].id, amount_money=-amount),
        ],
    )
    obligation_event_id = insert_inbound_event(session)
    obligation = SettlementObligation(
        journal_entry_id=entry.id,
        account_id=accounts["cash"].id,
        amount_money=amount,
        expected_settlement_date=date(2026, 9, 3),
        source_event_id=obligation_event_id,
    )
    session.add(obligation)
    session.flush()
    if status is SettlementObligationStatus.CONFIRMED:
        SettlementObligationRepository(_LedgerLikeUow(session)).confirm(
            obligation, confirmed_at=datetime.now(UTC)
        )
    elif status is SettlementObligationStatus.FAILED:
        SettlementObligationRepository(_LedgerLikeUow(session)).fail(
            obligation, failed_at=datetime.now(UTC), reason="bounced"
        )
    session.flush()
    return obligation


def test_no_obligations_settled_cash_is_fully_withdrawable_and_investable(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_deposit(db_committing, accounts, amount=Money("1000.00"))
    db_committing.commit()

    service = CashPolicyService(_LedgerLikeUow(db_committing), holds_provider=_FakeHoldsProvider())

    assert service.settled_cash(customer_id) == Money("1000.00")
    assert service.withdrawable(customer_id) == Money("1000.00")
    assert service.investable(customer_id) == Money("1000.00")


def test_one_pending_sell_counts_toward_investable_but_not_withdrawable(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_deposit(db_committing, accounts, amount=Money("1000.00"))
    _post_with_obligation(
        db_committing,
        accounts,
        entry_type=JournalEntryType.TRADE_SELL,
        amount=Money("300.00"),
        status=SettlementObligationStatus.PENDING,
    )
    db_committing.commit()

    service = CashPolicyService(_LedgerLikeUow(db_committing), holds_provider=_FakeHoldsProvider())

    assert service.settled_cash(customer_id) == Money("1000.00")
    assert service.unsettled_sale_proceeds(customer_id) == Money("300.00")
    assert service.withdrawable(customer_id) == Money("1000.00")
    assert service.investable(customer_id) == Money("1300.00")


def test_one_pending_deposit_counts_toward_investable_but_not_withdrawable(db_committing) -> None:
    """S1 §5's amendment: unsettled deposit proceeds are investable immediately, exactly as any
    other unsettled inflow -- but never withdrawable (the same asymmetry as a pending sell)."""
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_with_obligation(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("500.00"),
        status=SettlementObligationStatus.PENDING,
    )
    db_committing.commit()

    service = CashPolicyService(_LedgerLikeUow(db_committing), holds_provider=_FakeHoldsProvider())

    assert service.settled_cash(customer_id) == Money("0.00")
    assert service.unsettled_deposit_proceeds(customer_id) == Money("500.00")
    assert service.withdrawable(customer_id) == Money("0.00")
    assert service.investable(customer_id) == Money("500.00")


def test_one_failed_deposit_counts_toward_neither(db_committing) -> None:
    """FR-6: a bounced deposit is available for neither policy function -- excluded from
    settled_cash (never confirmed) and from unsettled_deposit_proceeds (no longer pending)."""
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_with_obligation(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("200.00"),
        status=SettlementObligationStatus.FAILED,
    )
    db_committing.commit()

    service = CashPolicyService(_LedgerLikeUow(db_committing), holds_provider=_FakeHoldsProvider())

    assert service.settled_cash(customer_id) == Money("0.00")
    assert service.unsettled_deposit_proceeds(customer_id) == Money("0.00")
    assert service.withdrawable(customer_id) == Money("0.00")
    assert service.investable(customer_id) == Money("0.00")


def test_confirmed_obligation_moves_its_cash_into_settled(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_with_obligation(
        db_committing,
        accounts,
        entry_type=JournalEntryType.TRADE_SELL,
        amount=Money("400.00"),
        status=SettlementObligationStatus.CONFIRMED,
    )
    db_committing.commit()

    service = CashPolicyService(_LedgerLikeUow(db_committing), holds_provider=_FakeHoldsProvider())

    assert service.settled_cash(customer_id) == Money("400.00")
    assert service.unsettled_sale_proceeds(customer_id) == Money("0.00")
    assert service.withdrawable(customer_id) == Money("400.00")
    assert service.investable(customer_id) == Money("400.00")


def test_holds_and_open_buy_commitments_reduce_the_respective_totals(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_deposit(db_committing, accounts, amount=Money("1000.00"))
    db_committing.commit()

    service = CashPolicyService(
        _LedgerLikeUow(db_committing),
        holds_provider=_FakeHoldsProvider(
            holds=Money("100.00"), open_buy_commitments=Money("50.00")
        ),
    )

    assert service.withdrawable(customer_id) == Money("900.00")
    assert service.investable(customer_id) == Money("850.00")


def test_free_riding_shaped_scenario_investable_reflects_the_still_unsettled_buy_funding(
    db_committing,
) -> None:
    """Bought using unsettled sale proceeds, then sold again before those proceeds confirm -- the
    scenario §5.1's guard flags. S1 does not implement the lot-to-obligation join that guard needs
    (S5's job); this asserts the *policy functions themselves* still compose correctly under that
    cash shape: the original sale's proceeds are investable-but-not-withdrawable throughout, and a
    second sale posts its own (also pending) proceeds on top."""
    customer_id = insert_customer(db_committing)
    accounts = _accounts(db_committing, customer_id)
    _post_deposit(db_committing, accounts, amount=Money("100.00"))  # a settled cash floor
    _post_with_obligation(
        db_committing,
        accounts,
        entry_type=JournalEntryType.TRADE_SELL,
        amount=Money("500.00"),
        status=SettlementObligationStatus.PENDING,
    )
    # A second sell, funded (economically) by the still-unsettled proceeds above -- the free-
    # riding shape. Its own obligation is also pending.
    _post_with_obligation(
        db_committing,
        accounts,
        entry_type=JournalEntryType.TRADE_SELL,
        amount=Money("200.00"),
        status=SettlementObligationStatus.PENDING,
    )
    db_committing.commit()

    service = CashPolicyService(_LedgerLikeUow(db_committing), holds_provider=_FakeHoldsProvider())

    assert service.settled_cash(customer_id) == Money("100.00")
    assert service.unsettled_sale_proceeds(customer_id) == Money("700.00")
    assert service.withdrawable(customer_id) == Money("100.00")
    assert service.investable(customer_id) == Money("800.00")
