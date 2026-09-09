"""Each of the 5 paginated endpoints' cursor-key tuples (S12 §8) round-trips through
`encode_cursor`/`decode_cursor` with the correct arity and types. This is a contract test for the
shape each endpoint's own `_decode_*_cursor` helper depends on -- it does not exercise those
helpers directly (they live in `app/controllers/api/*.py`), only the shared primitive underneath.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.core.pagination import decode_cursor, encode_cursor

# --- GET /orders: (created_at, id) DESC ---------------------------------------------------------


def test_orders_cursor_key_round_trips() -> None:
    created_at = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    order_id = uuid.uuid4()

    cursor = encode_cursor(created_at.isoformat(), str(order_id))
    decoded = decode_cursor(cursor)

    assert len(decoded) == 2
    assert datetime.fromisoformat(decoded[0]) == created_at  # type: ignore[arg-type]
    assert uuid.UUID(decoded[1]) == order_id  # type: ignore[arg-type]


# --- GET /lots: (acquired_at, id) ASC ------------------------------------------------------------


def test_lots_cursor_key_round_trips() -> None:
    acquired_at = date(2026, 1, 5)
    lot_id = uuid.uuid4()

    cursor = encode_cursor(acquired_at.isoformat(), str(lot_id))
    decoded = decode_cursor(cursor)

    assert len(decoded) == 2
    assert date.fromisoformat(decoded[0]) == acquired_at  # type: ignore[arg-type]
    assert uuid.UUID(decoded[1]) == lot_id  # type: ignore[arg-type]


# --- GET /funding/history: (effective_date, recorded_at, journal_entry_id) DESC ------------------


def test_funding_history_cursor_key_round_trips() -> None:
    effective_date = date(2026, 9, 1)
    recorded_at = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
    journal_entry_id = uuid.uuid4()

    cursor = encode_cursor(
        effective_date.isoformat(), recorded_at.isoformat(), str(journal_entry_id)
    )
    decoded = decode_cursor(cursor)

    assert len(decoded) == 3
    assert date.fromisoformat(decoded[0]) == effective_date  # type: ignore[arg-type]
    assert datetime.fromisoformat(decoded[1]) == recorded_at  # type: ignore[arg-type]
    assert uuid.UUID(decoded[2]) == journal_entry_id  # type: ignore[arg-type]


# --- GET /valuation/history: (effective_date, recorded_at, posting_id) DESC ----------------------


def test_valuation_history_cursor_key_round_trips() -> None:
    """`posting_id` never appears in `HistoryEntryResponse` -- the cursor is opaque, so this only
    proves the round-trip, not that the field is surfaced anywhere in the response body."""
    effective_date = date(2026, 9, 1)
    recorded_at = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
    posting_id = uuid.uuid4()

    cursor = encode_cursor(effective_date.isoformat(), recorded_at.isoformat(), str(posting_id))
    decoded = decode_cursor(cursor)

    assert len(decoded) == 3
    assert date.fromisoformat(decoded[0]) == effective_date  # type: ignore[arg-type]
    assert datetime.fromisoformat(decoded[1]) == recorded_at  # type: ignore[arg-type]
    assert uuid.UUID(decoded[2]) == posting_id  # type: ignore[arg-type]


# --- GET /statements: (period_start, id) DESC -----------------------------------------------------


def test_statements_cursor_key_round_trips() -> None:
    period_start = date(2026, 8, 1)
    snapshot_id = uuid.uuid4()

    cursor = encode_cursor(period_start.isoformat(), str(snapshot_id))
    decoded = decode_cursor(cursor)

    assert len(decoded) == 2
    assert date.fromisoformat(decoded[0]) == period_start  # type: ignore[arg-type]
    assert uuid.UUID(decoded[1]) == snapshot_id  # type: ignore[arg-type]
