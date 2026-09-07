# 25 — Order cancellation is a broker request, never a local state mutation

## Status

Accepted

## Context

S3 §6 exposes create/approve/read on `/api/v1/orders` but no cancel route; `OrderStatus.CANCELED`
already exists in the state machine and `TERMINAL_NON_FILLED_STATUSES` (`app/models/orders/order.py`),
and `ApprovalHoldReleaseReason.CANCELED` already exists on `approval_hold`
(`app/models/orders/approval_hold.py`) — but both are currently inbound-only: nothing initiates a
cancellation, only a broker-confirmed `canceled` trade-update (ADR 22) ever produces one, via
`AlpacaTradeUpdateHandler` → `OrderProjectionService.apply_new_event` → `fold()`.

Adding customer-initiated cancellation must not disturb that invariant. Alpaca's Trading API (ADR
21) accepts a cancel request but does not guarantee it: the order can still fill before the cancel
is processed broker-side. `BrokerPort` (`app/integrations/ports.py`) today only declares
`submit_order`; there is no `cancel_order`.

## Decision

### Cancellation is a request, not a transition

`POST /api/v1/orders/<order_id>/cancel` calls `OrderService.request_cancel(order_id, broker=...)`,
which:

1. Tenant-scoped `get_for_update` (identical ownership check to `approve`) — another customer's
   order is invisible, not merely forbidden.
2. Rejects (`OrderNotCancellableError`, mapped to `409`) any order outside `_CANCELLABLE_STATUSES`
   = `{submitted, accepted, partially_filled}` — i.e. an order already at the broker but not yet
   in a terminal state. Pre-broker orders (`draft`/`awaiting_approval`/`approved`) have no broker
   order to cancel; every terminal status (`filled`/`rejected`/`canceled`/`expired`) is, by
   definition, no longer cancellable.
3. Reads the `broker_order_id` off the order's own `submitted` `order_event` payload (already
   recorded by `submit_to_broker`'s `_synthesize_event`) and calls `BrokerPort.cancel_order(...)`.
4. **Never sets `order.status` and never touches the `approval_hold`.** The only path that ever
   transitions an order to `canceled` is the existing one: Alpaca's `trade_updates` websocket
   (ADR 22) → `AlpacaTradeUpdateHandler` → `OrderProjectionService.apply_new_event` → `fold()`.
   `request_cancel` is deliberately symmetric with every other inbound-only terminal
   transition — it can *ask*, it cannot *decide*.

This means the broker may still fill the order after accepting the cancel request. That is treated
as a correct, expected outcome of asking rather than deciding, not a bug: whichever event lands
first on the websocket — `fill` or `canceled` — wins, exactly as `fold()` already handles any other
event ordering.

### `BrokerPort.cancel_order`

```python
def cancel_order(self, *, broker_order_id: str) -> None: ...
```

Added to the `BrokerPort` protocol (`app/integrations/ports.py`), implemented by
`AlpacaBrokerAdapter.cancel_order` (wraps the Alpaca SDK's `TradingClient.cancel_order_by_id`,
raising `alpaca.common.exceptions.APIError` uncaught — matching `submit_order`'s existing posture)
and by `FakeBrokerAdapter.cancel_order` (records the call in `self.cancel_requests`, the test
double's assertion surface).

### Synchronous, not outbox-enqueued

`request_cancel` calls the broker directly inside the `/cancel` request, not via `job_outbox` the
way `submit_order_to_broker` is. This mirrors this codebase's existing precedent for synchronous,
customer-facing provider calls — `identity.py`'s `_build_kyc_port`/`StripeKycAdapter` and
`funding.py`'s `_plaid_adapter`/`PlaidBankAdapter` are both constructed and called directly inside
their controllers, not queued. `_build_broker_port()` in `orders.py` follows the identical shape
(reads Alpaca credentials from settings, raises if unconfigured, monkeypatchable in tests) rather
than adding a new composition-root wiring pattern.

### Idempotency

A repeated cancel request while the order is still in `_CANCELLABLE_STATUSES` simply re-issues
`BrokerPort.cancel_order` — treated as a no-op success (`200`), since Alpaca's own cancel-order
endpoint is idempotent (canceling an order that already has a pending cancel does nothing extra).
No new "cancel already requested" column or state is introduced. Once the order leaves that set —
confirmed `canceled`, or raced into `filled`/any other terminal — a further request is a `409`
(`OrderNotCancellableError`), which is the natural boundary rather than a special-cased response.

### Hold release is unchanged

The buy-side `approval_hold` is already released the moment an order reaches `submitted`
(`ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED`, in `OrderProjectionService`). Since
`_CANCELLABLE_STATUSES` starts at `submitted`, every order this feature can cancel has *already*
had its hold released before a cancel is ever requested. `request_cancel` does not touch the hold;
`ApprovalHoldReleaseReason.CANCELED`'s release branch (already wired in
`OrderProjectionService._release_reason_by_terminal_status`) fires when the broker-confirmed
`canceled` event lands, but resolves as an idempotent no-op (`ApprovalHoldService.release` returns
immediately once a hold is already `released`) — correct, not dead code: it stays the live path for
any future cancellation of a pre-submission order, which is explicitly out of scope here (next
section).

### Auditing

The write is `@audited("orders.cancel_requested")`, via the same indirection-function pattern
`admin/kyc_overrides.py` already uses (`@audited` introspects a `uow` argument from the call frame,
which a bare Flask route handler doesn't expose without one). Note: `approve_order`'s route is
*not* currently `@audited` — this ADR does not retrofit it, but does not repeat its omission
either; every privileged write from this point forward should be, per the backend engineering
invariant, and `/cancel` is the first to comply.

## Consequences

- The fill-races-cancel case is a first-class, tested outcome: requesting a cancel on a
  `submitted`/`accepted`/`partially_filled` order and then delivering a `fill` trade-update through
  the existing handler still lands the order on `filled`, never `canceled` — no special-casing
  needed, because `request_cancel` never wrote to `order.status` in the first place.
- `200` from `/cancel` means "the broker was asked to cancel", not "the order is canceled" — a
  client must still read the order's `status` (or the event stream) to see the outcome.
- Pre-submission cancellation (`draft`/`awaiting_approval`/`approved`) is explicitly out of scope.
  There is no broker order to cancel yet, so `BrokerPort.cancel_order` cannot apply; locally
  transitioning such an order to `canceled` would need its own, separate decision (no broker call,
  immediate hold release, since nothing is broker-visible yet) — a materially different, simpler
  mechanism this ADR deliberately does not fold in.
- `orders.py`'s controller now imports `app.integrations.alpaca.broker_adapter` directly, which
  `import-linter`'s `layers`/`services-use-ports-only` contracts permit (they constrain
  `app.services`, not `app.controllers`) and which `funding.py`/`fees.py`/`identity.py` already do
  for their own synchronous provider calls — consistent with, not a new exception to, the existing
  architecture.

## Alternatives considered

- **Locally set `OrderStatus.CANCELED` at request time, correct it later if a fill arrives.**
  Rejected outright: this is exactly the race the brief warns about ("Alpaca may still fill the
  order after accepting the cancel request") and would require an un-cancel transition nothing else
  in the state machine has, plus a customer-visible status that can silently reverse itself.
- **Enqueue an outbox task (`cancel_order_at_broker`), mirroring `submit_order_to_broker`.**
  Considered for symmetry with submission. Rejected: submission is queued because it must
  eventually succeed with retry semantics; a cancel request has no such requirement — a failed
  attempt is safe for the client to retry idempotently, and the customer benefits more from a
  synchronous "the broker has been asked" confirmation than from a fire-and-forget `202`. Kept as
  the natural fallback if operational experience shows synchronous Alpaca calls from the request
  path are too slow/unreliable.
- **A new "cancel requested" flag/timestamp column on `order`, for a distinct "already requested"
  idempotency response.** Rejected: no observable behavior needs it — a repeated request while
  still cancellable is indistinguishable, from the client's point of view, from the first request
  (both mean "the broker has been (re-)asked"), and the broker's own idempotent cancel semantics
  already cover the safety property. Adding state to distinguish "first" from "repeated" would be
  tracking information nothing reads.
- **Allow pre-submission cancellation in the same endpoint, branching on status (broker call for
  post-submission, local transition for pre-submission).** Rejected for this ADR: conflates two
  different mechanisms (broker request vs. local mutation) behind one endpoint and one service
  method, when the brief's explicit non-negotiable is specifically about the post-submission race.
  Left as a clearly-scoped follow-on if product asks for it.
