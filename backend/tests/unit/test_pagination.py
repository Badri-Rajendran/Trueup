"""Cursor pagination: opaque, tamper-evident cursors and the limit+1 `has_more` trick (S0 §8)."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from app.core.errors import ValidationError
from app.core.pagination import (
    MAX_PAGE_SIZE,
    Page,
    decode_cursor,
    encode_cursor,
    normalize_limit,
    paginate,
)

# --- cursor round-trip -------------------------------------------------------------------------


def test_round_trips_a_single_value() -> None:
    cursor = encode_cursor("2026-09-04T12:00:00+00:00")
    assert decode_cursor(cursor) == ("2026-09-04T12:00:00+00:00",)


def test_round_trips_a_compound_key() -> None:
    """A timestamp alone is not unique; the id breaks the tie."""
    cursor = encode_cursor("2026-09-04T12:00:00+00:00", 42)
    assert decode_cursor(cursor) == ("2026-09-04T12:00:00+00:00", 42)


def test_round_trips_every_json_scalar_type() -> None:
    cursor = encode_cursor("s", 1, 1.5, True, None)
    assert decode_cursor(cursor) == ("s", 1, 1.5, True, None)


def test_cursor_is_url_safe() -> None:
    cursor = encode_cursor("a value/with+chars", 1)
    assert "/" not in cursor
    assert "+" not in cursor


def test_encode_requires_at_least_one_value() -> None:
    with pytest.raises(ValueError, match="at least one"):
        encode_cursor()


# --- malformed / hostile cursors never raise anything but ValidationError ----------------------


def test_decode_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        decode_cursor("")


def test_decode_rejects_garbage_input() -> None:
    with pytest.raises(ValidationError):
        decode_cursor("not-a-valid-cursor-at-all-!!!")


def test_decode_rejects_truncated_cursor() -> None:
    cursor = encode_cursor("2026-09-04T12:00:00+00:00", 42)
    with pytest.raises(ValidationError):
        decode_cursor(cursor[: len(cursor) // 2])


def test_decode_rejects_tampered_payload() -> None:
    """A single flipped character must fail the checksum, never decode to a different sort key."""
    cursor = encode_cursor("2026-09-04T12:00:00+00:00", 42)
    flipped_char = "A" if cursor[10] != "A" else "B"
    tampered = cursor[:10] + flipped_char + cursor[11:]
    with pytest.raises(ValidationError):
        decode_cursor(tampered)


def test_decode_rejects_oversized_cursor() -> None:
    huge = "A" * 100_000
    with pytest.raises(ValidationError):
        decode_cursor(huge)


def test_decode_rejects_non_list_payload() -> None:
    """A checksum-consistent cursor whose payload isn't the expected list shape must be rejected."""
    payload = json.dumps({"not": "a list"}).encode("utf-8")
    checksum = hashlib.sha256(payload).digest()[:16]
    hostile = base64.urlsafe_b64encode(payload + checksum).decode("ascii").rstrip("=")
    with pytest.raises(ValidationError):
        decode_cursor(hostile)


def test_decode_error_never_echoes_the_input_cursor() -> None:
    hostile_cursor = "super-secret-token-fragment"
    with pytest.raises(ValidationError) as excinfo:
        decode_cursor(hostile_cursor)
    assert hostile_cursor not in str(excinfo.value)


# --- limit validation (OWASP API4) ---------------------------------------------------------------


def test_normalize_limit_defaults_when_none() -> None:
    assert normalize_limit(None, default=25) == 25


def test_normalize_limit_accepts_a_valid_value() -> None:
    assert normalize_limit(10) == 10


def test_normalize_limit_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        normalize_limit(0)


def test_normalize_limit_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        normalize_limit(-5)


def test_normalize_limit_rejects_over_maximum() -> None:
    with pytest.raises(ValidationError):
        normalize_limit(MAX_PAGE_SIZE + 1)


def test_normalize_limit_accepts_the_maximum_exactly() -> None:
    assert normalize_limit(MAX_PAGE_SIZE) == MAX_PAGE_SIZE


# --- Page / has_more ------------------------------------------------------------------------------


def test_page_has_more_is_true_with_a_next_cursor() -> None:
    page: Page[int] = Page(items=(1, 2), next_cursor=encode_cursor(2))
    assert page.has_more is True


def test_page_has_more_is_false_without_a_next_cursor() -> None:
    page: Page[int] = Page(items=(1, 2), next_cursor=None)
    assert page.has_more is False


# --- paginate(): the limit+1 technique -----------------------------------------------------------


def test_paginate_detects_more_rows_via_limit_plus_one() -> None:
    rows = [(0, "a"), (1, "b"), (2, "c")]  # limit=2, so 3 rows means "more exist"
    page = paginate(rows, limit=2, cursor_key=lambda row: (row[0],))
    assert page.items == ((0, "a"), (1, "b"))
    assert page.has_more is True
    assert decode_cursor(page.next_cursor or "") == (1,)


def test_paginate_reports_no_more_rows_when_exactly_at_the_limit() -> None:
    rows = [(0, "a"), (1, "b")]
    page = paginate(rows, limit=2, cursor_key=lambda row: (row[0],))
    assert page.items == ((0, "a"), (1, "b"))
    assert page.has_more is False
    assert page.next_cursor is None


def test_paginate_reports_no_more_rows_when_under_the_limit() -> None:
    rows = [(0, "a")]
    page = paginate(rows, limit=2, cursor_key=lambda row: (row[0],))
    assert page.has_more is False


def test_paginate_cursor_breaks_ties_on_the_compound_key() -> None:
    """Two rows sharing a timestamp: the id makes the next-page boundary unambiguous."""
    same_ts = "2026-09-04T12:00:00+00:00"
    rows = [
        (same_ts, 1, "first"),
        (same_ts, 2, "second"),
        (same_ts, 3, "third"),
    ]
    page = paginate(rows, limit=2, cursor_key=lambda row: (row[0], row[1]))
    assert page.has_more is True
    assert decode_cursor(page.next_cursor or "") == (same_ts, 2)
