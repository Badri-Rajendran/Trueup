"""S13 §7: a minimal MCP client calling all six tools end-to-end against a running `app.mcp`
server, over real streamable-HTTP with a real `mcp.ClientSession`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import socket
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import uvicorn
from sqlalchemy import text

from app.config import Settings
from app.core.crypto import reset_cipher, set_cipher
from app.extensions import dispose_engines, init_engines
from app.integrations.crypto.local_cipher import LocalDevCipher
from app.mcp import build_server
from app.models.chat.curated_views import (
    CREATE_CURATED_VIEWS_SQL,
    DROP_CURATED_VIEWS_SQL,
    GRANT_CURATED_VIEWS_SQL,
)
from app.models.identity.bank_link import BankLink
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.identity.staff import Staff, StaffRole
from app.models.identity.staff_api_token import StaffApiToken
from app.models.ledger.account import Account
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.posting import Posting
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.security import Security
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.ops.admin_audit_log import AdminAuditLog
from app.models.ops.agent_action_request import AgentActionRequest, AgentActionStatus
from app.models.ops.inbound_event import InboundEvent
from app.models.orders.order import Order
from app.models.orders.order_event import OrderEvent
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.reconciliation.reconciliation_break import (
    ReconciliationBreak,
    ReconciliationBreakStatus,
    ReconciliationBreakType,
)
from app.models.restatement.published_snapshot import PublishedSnapshot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

# Every table each curated view reads from, plus S13's own new tables.
_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    Security.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
    SubPeriodReturn.__table__,
    PublishedSnapshot.__table__,
    BankLink.__table__,
    AdminAuditLog.__table__,
    Staff.__table__,
    StaffApiToken.__table__,
    AgentActionRequest.__table__,
    ReconciliationBreak.__table__,
    ModelPortfolio.__table__,
    CustomerModelAssignment.__table__,
]


@pytest.fixture
def agent_surface_schema(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    with owner_engine.begin() as connection:
        connection.execute(text(CREATE_CURATED_VIEWS_SQL))
        connection.execute(text(GRANT_CURATED_VIEWS_SQL))
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text(DROP_CURATED_VIEWS_SQL))
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


@pytest.fixture
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    set_cipher(LocalDevCipher(base64.b64encode(b"0" * 32).decode()))
    yield None
    dispose_engines()
    reset_cipher()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _ServerThread(threading.Thread):
    """Runs `uvicorn.Server.serve()` in its own event loop on a background thread."""

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(daemon=True)
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        asyncio.run(self.server.serve())

    def wait_until_ready(self, *, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("MCP server did not start in time")
            time.sleep(0.02)

    def stop(self) -> None:
        self.server.should_exit = True


def _insert_staff_and_token(owner_engine: Engine, *, raw_token: str) -> tuple[uuid.UUID, uuid.UUID]:
    staff_id = uuid.uuid4()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO staff (id, email, password_hash, role) "
                "VALUES (:id, :email, 'x', :role)"
            ),
            {"id": staff_id, "email": f"{staff_id}@trueup.test", "role": StaffRole.adviser.value},
        )
        token_id = uuid.uuid4()
        connection.execute(
            text(
                "INSERT INTO staff_api_token (id, staff_id, label, token_hash) "
                "VALUES (:id, :staff_id, 'contract test token', :token_hash)"
            ),
            {"id": token_id, "staff_id": staff_id, "token_hash": token_hash},
        )
    return staff_id, token_id


def _insert_customer(owner_engine: Engine) -> uuid.UUID:
    customer_id = uuid.uuid4()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO customer (id, email, password_hash, kyc_status, "
                "account_approval_status) VALUES (:id, :email, :ph, :kyc, :aa)"
            ),
            {
                "id": customer_id,
                "email": f"{customer_id}@trueup.test",
                "ph": "hash",
                "kyc": KycStatus.rejected.value,
                "aa": AccountApprovalStatus.pending.value,
            },
        )
    return customer_id


def _insert_break(owner_engine: Engine, *, customer_id: uuid.UUID) -> uuid.UUID:
    break_id = uuid.uuid4()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reconciliation_break "
                "(id, break_type, customer_id, opened_at, status, import_batch_id) "
                "VALUES (:id, :bt, :cid, :opened_at, :status, :batch)"
            ),
            {
                "id": break_id,
                "bt": ReconciliationBreakType.CASH_MISMATCH.value,
                "cid": customer_id,
                "opened_at": datetime.now(UTC),
                "status": ReconciliationBreakStatus.OPEN.value,
                "batch": uuid.uuid4(),
            },
        )
    return break_id


async def _call_all_six_tools(
    *, port: int, raw_token: str, break_id: uuid.UUID, customer_id: uuid.UUID
) -> dict[str, object]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = f"http://127.0.0.1:{port}/mcp"
    results: dict[str, object] = {}
    headers = {"Authorization": f"Bearer {raw_token}"}
    async with (
        httpx2.AsyncClient(headers=headers) as http_client,
        streamable_http_client(url, http_client=http_client) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        results["breaks"] = await session.call_tool("list_open_reconciliation_breaks", {})
        results["portfolio"] = await session.call_tool(
            "get_portfolio_summary", {"customer_id": str(customer_id)}
        )
        results["history"] = await session.call_tool(
            "get_transaction_history", {"customer_id": str(customer_id)}
        )
        results["propose_break"] = await session.call_tool(
            "propose_reconciliation_break_resolution",
            {"break_id": str(break_id), "resolution_note": "confirmed with custodian"},
        )
        results["propose_kyc"] = await session.call_tool(
            "propose_kyc_override",
            {"customer_id": str(customer_id), "reason": "confirmed manually"},
        )
        results["propose_rebalance"] = await session.call_tool(
            "propose_rebalance", {"customer_id": str(customer_id)}
        )
    return results


async def _call_with_bad_token(*, port: int) -> object:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = f"http://127.0.0.1:{port}/mcp"
    headers = {"Authorization": "Bearer not-a-real-token"}
    async with (
        httpx2.AsyncClient(headers=headers) as http_client,
        streamable_http_client(url, http_client=http_client) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool("list_open_reconciliation_breaks", {})


@pytest.mark.usefixtures("_engines", "agent_surface_schema")
def test_all_six_tools_end_to_end_over_real_streamable_http(owner_engine: Engine) -> None:
    raw_token = "contract-test-token-" + uuid.uuid4().hex
    _insert_staff_and_token(owner_engine, raw_token=raw_token)
    customer_id = _insert_customer(owner_engine)
    break_id = _insert_break(owner_engine, customer_id=customer_id)

    port = _free_port()
    config = uvicorn.Config(
        build_server().streamable_http_app(host="127.0.0.1"),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server_thread = _ServerThread(config)
    server_thread.start()
    try:
        server_thread.wait_until_ready()
        results = asyncio.run(
            _call_all_six_tools(
                port=port, raw_token=raw_token, break_id=break_id, customer_id=customer_id
            )
        )
    finally:
        server_thread.stop()
        server_thread.join(timeout=5)

    breaks_result = results["breaks"]
    assert breaks_result.is_error is not True  # type: ignore[attr-defined]

    for key in ("propose_break", "propose_kyc", "propose_rebalance"):
        result = results[key]
        assert result.is_error is not True, f"{key} failed: {result}"  # type: ignore[attr-defined]

    # The write tools recorded proposals only -- nothing executed (ADR 24's whole point).
    with owner_engine.begin() as connection:
        pending_count = connection.execute(
            text("SELECT count(*) FROM agent_action_request WHERE status = :status"),
            {"status": AgentActionStatus.PENDING.value},
        ).scalar_one()
        assert pending_count == 3

        break_status = connection.execute(
            text("SELECT status FROM reconciliation_break WHERE id = :id"), {"id": break_id}
        ).scalar_one()
        assert break_status == ReconciliationBreakStatus.OPEN.value

        kyc_status = connection.execute(
            text("SELECT kyc_status FROM customer WHERE id = :id"), {"id": customer_id}
        ).scalar_one()
        assert kyc_status == KycStatus.rejected.value  # untouched by the write tool


@pytest.mark.usefixtures("_engines", "agent_surface_schema")
def test_an_invalid_bearer_token_is_rejected(owner_engine: Engine) -> None:
    port = _free_port()
    config = uvicorn.Config(
        build_server().streamable_http_app(host="127.0.0.1"),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server_thread = _ServerThread(config)
    server_thread.start()
    try:
        server_thread.wait_until_ready()
        result = asyncio.run(_call_with_bad_token(port=port))
    finally:
        server_thread.stop()
        server_thread.join(timeout=5)

    assert result.is_error is True  # type: ignore[attr-defined]
