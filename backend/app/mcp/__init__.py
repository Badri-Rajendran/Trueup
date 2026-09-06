"""S13's MCP server (ADR 24). Entry-point layer alongside `app/controllers/`."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from app.mcp.read_tools import (
    get_portfolio_summary,
    get_transaction_history,
    list_open_reconciliation_breaks,
)
from app.mcp.write_tools import (
    propose_kyc_override,
    propose_rebalance,
    propose_reconciliation_break_resolution,
)

_INSTRUCTIONS = (
    "Trueup agent surface (ADR 24, S13). Three read tools (get_portfolio_summary, "
    "get_transaction_history, list_open_reconciliation_breaks) answer questions against curated, "
    "read-only views. Three write tools (propose_reconciliation_break_resolution, "
    "propose_kyc_override, propose_rebalance) never change state directly -- each records a "
    "pending proposal that a human adviser or admin must separately review and approve before "
    "anything happens. Every call requires a Bearer staff_api_token."
)


def build_server() -> MCPServer:
    server = MCPServer(name="trueup-agent-surface", instructions=_INSTRUCTIONS)

    server.add_tool(
        get_portfolio_summary,
        name="get_portfolio_summary",
        description="Balance, holdings, and assigned model for one customer.",
    )
    server.add_tool(
        get_transaction_history,
        name="get_transaction_history",
        description="One customer's transaction history, optionally since a given timestamp.",
    )
    server.add_tool(
        list_open_reconciliation_breaks,
        name="list_open_reconciliation_breaks",
        description="The aged queue of open reconciliation breaks, oldest first.",
    )
    server.add_tool(
        propose_reconciliation_break_resolution,
        name="propose_reconciliation_break_resolution",
        description=(
            "Propose resolving a reconciliation break. Records a pending approval request; "
            "never resolves the break itself."
        ),
    )
    server.add_tool(
        propose_kyc_override,
        name="propose_kyc_override",
        description=(
            "Propose reopening a locked customer's KYC status. Records a pending approval "
            "request; never changes KYC status itself."
        ),
    )
    server.add_tool(
        propose_rebalance,
        name="propose_rebalance",
        description=(
            "Propose an ad-hoc drift evaluation and rebalance for one customer, ahead of the "
            "monthly schedule. Records a pending approval request; never places an order itself."
        ),
    )

    return server


__all__ = ["build_server"]
