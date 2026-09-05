# 5 — Withdrawable vs. investable cash, with a free-riding guard

## Status

Accepted

## Context

FR-13 states the one hard constraint explicitly: proceeds that have not settled cannot be
withdrawn. It says nothing about whether *unsettled* sale proceeds may be *reinvested* before
settlement confirms. Those are two different policies over the same account state (ADR 2:
available cash is a computed function, not a stored balance), and conflating them either violates
the withdrawal constraint or forces every monthly rebalance (FR-28) to either split across two days
— leaving the book mid-flight overnight, which FR-29 already anticipates as a real condition — or
hold a standing cash buffer sized to fund every buy, which is a permanent drag on returns.

## Decision

Two pure policy functions over the same ledger and obligation state:

- **`withdrawable = settled_cash - holds`** — the brief's one hard constraint. Only confirmed,
  settled cash, minus any approval-pending holds (ADR 7).
- **`investable = settled_cash + unsettled_sale_proceeds - open_buy_commitments - holds`** —
  additionally counts unsettled sale proceeds, permitted in a cash account. This lets a monthly
  rebalance sell and buy the same day without a standing cash drag.

A **free-riding guard** flags a violation when a position is sold while the obligation that funded
its purchase is still unconfirmed (i.e., bought with unsettled proceeds, then sold again before
those proceeds settled).

Implementation shape:
- **Settled cash stays a pooled, fungible figure** — no provenance tracking needed for it.
- **Only unsettled inflows are discrete**, and each already exists as a settlement obligation
  (ADR 2) — provenance is a link from a buy to the obligation(s) that funded it, not a new entity.
- **Buys consume settled cash first, then unsettled cash ordered by soonest expected settlement.**
  This makes provenance a deterministic consequence of a consumption-ordering rule rather than
  something tagged by hand, and structurally minimizes how often the guard can fire.

## Consequences

- The free-riding guard's join is cheap: "was this position funded by an obligation unconfirmed at
  time of sale?" — one query over data ADR 2 already produces.
- Given monthly buy-and-hold rebalancing, the guard is expected to be rare by construction: it only
  fires when a customer-initiated sell happens within roughly a day of a rebalance buy funded by
  unsettled proceeds.
- Two policy functions must be kept clearly distinguished in every consuming surface (order
  placement uses `investable`; withdrawal requests use `withdrawable`) — a swap between them is a
  regulatory-grade bug, not a cosmetic one.

## Alternatives considered

- **One conservative number** (`withdrawable == investable`, settled cash only). Simplest possible
  rule, and structurally makes free-riding impossible — but forces every monthly rebalance to
  either split across two days (book exposed overnight) or carry a standing cash buffer, a
  permanent drag on returns. Rejected as too costly for a product whose whole point is model
  portfolio performance.
- **Two policies without a free-riding guard.** Simpler to build, but leaves a known regulatory
  exposure (using unsettled proceeds' economic value to fund a purchase, then selling before they
  settle) undetected. Rejected for a regulated platform (root `CLAUDE.md`: OWASP/ASVS discipline
  extends to domain-level compliance, not just application security).
