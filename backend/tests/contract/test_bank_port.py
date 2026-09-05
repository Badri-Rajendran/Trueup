"""`BankPort` contract (S2 §8): the same assertions against `FakeBankAdapter` and, when Plaid
sandbox credentials plus a real sandbox public token are configured, `PlaidBankAdapter` -- so the
fake cannot silently drift from the real provider it stands in for (`backend/CLAUDE.md`).
"""

from __future__ import annotations

import os

import pytest

from app.integrations.fake.fake_bank import FakeBankAdapter
from app.integrations.ports import BankPort


def _assert_valid_handle(port: BankPort, *, public_token: str) -> None:
    handle = port.exchange_public_token(public_token=public_token)
    assert handle.plaid_item_id
    assert handle.access_token


def test_fake_bank_adapter_satisfies_the_contract() -> None:
    _assert_valid_handle(FakeBankAdapter(), public_token="public-sandbox-fake-token")


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not (os.environ.get("PLAID_CLIENT_ID") and os.environ.get("PLAID_SECRET")
         and os.environ.get("PLAID_SANDBOX_PUBLIC_TOKEN")),
    reason=(
        "requires Plaid sandbox credentials (PLAID_CLIENT_ID/PLAID_SECRET) plus a public token "
        "minted via Plaid's sandbox Link flow (PLAID_SANDBOX_PUBLIC_TOKEN)"
    ),
)
def test_real_plaid_bank_adapter_satisfies_the_contract() -> None:
    from app.integrations.plaid.bank_adapter import PlaidBankAdapter

    port = PlaidBankAdapter(
        client_id=os.environ["PLAID_CLIENT_ID"], secret=os.environ["PLAID_SECRET"]
    )
    _assert_valid_handle(port, public_token=os.environ["PLAID_SANDBOX_PUBLIC_TOKEN"])
