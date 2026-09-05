"""Cursor-based pagination (S0 §8).

Offset pagination (`LIMIT`/`OFFSET`) on an append-only, ever-growing ledger degrades as the offset
grows, and — worse — can skip or duplicate rows when a concurrent insert shifts the window mid-scan.
This module exists so no list endpoint (transaction history, tax lots, reconciliation breaks) has
to reach for `OFFSET` at all: a cursor names the last row a caller has seen by its sort key, and the
next page asks for rows strictly after it.

A cursor must be built from a **compound, unique sort key** — `(timestamp, id)`, never a bare
timestamp. Two rows sharing the same instant are unremarkable in a system that posts several ledger
legs together in one transaction; a cursor that cannot break the tie deterministically will skip or
repeat whichever row sits on the page boundary.

The cursor is opaque to the client (a base64url token, not a raw offset or row id to probe) and
tamper-evident: the encoded payload carries a checksum of itself, so a corrupted, truncated, or
hand-edited cursor is rejected as a clean `ValidationError` — never a 500, never a silently
mis-paged result. The checksum is a *corruption* detector, not an authorization boundary: every
repository query built from a decoded cursor is still tenant-scoped and re-validated like any other
input, so a client crafting its own well-formed cursor gains nothing beyond choosing which of its
own rows to page from.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

CursorValue = str | int | float | bool | None
"""The scalar types one component of a sort key may hold. JSON-native, so a cursor round-trips
exactly, with no lossy string coercion of numbers or booleans."""

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
"""Enforced on every list endpoint (OWASP API4 — unrestricted resource consumption). No caller,
including an internal one, may request an unbounded page."""

_MAX_CURSOR_LENGTH = 2048
"""Generously larger than any realistic sort key; rejects an oversized token before it is parsed."""

_CHECKSUM_BYTES = 16


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a cursor-paginated list.

    `next_cursor` is `None` exactly when there is no further page. `has_more` is derived from it
    rather than stored separately, so the two can never disagree with each other.
    """

    items: tuple[T, ...]
    next_cursor: str | None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def normalize_limit(
    limit: int | None,
    *,
    default: int = DEFAULT_PAGE_SIZE,
    maximum: int = MAX_PAGE_SIZE,
) -> int:
    """Validate a client-supplied page size, or apply the default when the client gave none.

    Rejects a non-positive or oversized value outright, rather than silently clamping it — clamping
    would let a caller believe it asked for 100,000 rows and quietly received 200, which is a worse
    failure mode for a paging client than an explicit `422`.
    """
    if limit is None:
        return default
    if limit <= 0:
        raise ValidationError("limit must be a positive integer")
    if limit > maximum:
        raise ValidationError(f"limit must not exceed {maximum}")
    return limit


def encode_cursor(*values: CursorValue) -> str:
    """Encode a compound sort key into an opaque, tamper-evident cursor.

    Pass every component of the sort key the query orders by, in order — e.g.
    `encode_cursor(posting.recorded_at.isoformat(), posting.id)`.
    """
    if not values:
        raise ValueError("encode_cursor requires at least one sort-key value")
    payload = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    checksum = hashlib.sha256(payload).digest()[:_CHECKSUM_BYTES]
    return base64.urlsafe_b64encode(payload + checksum).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[CursorValue, ...]:
    """Decode and verify a cursor produced by `encode_cursor`.

    Never raises anything but `ValidationError`, and never echoes the offending input back in the
    error — a malformed cursor is client input to reject cleanly, not server state to explain.
    """
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise ValidationError("invalid pagination cursor")

    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError):
        raise ValidationError("invalid pagination cursor") from None

    if len(raw) <= _CHECKSUM_BYTES:
        raise ValidationError("invalid pagination cursor")

    payload, checksum = raw[:-_CHECKSUM_BYTES], raw[-_CHECKSUM_BYTES:]
    expected = hashlib.sha256(payload).digest()[:_CHECKSUM_BYTES]
    if not hmac.compare_digest(checksum, expected):
        raise ValidationError("invalid pagination cursor")

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        raise ValidationError("invalid pagination cursor") from None

    if not isinstance(decoded, list) or not decoded:
        raise ValidationError("invalid pagination cursor")
    for item in decoded:
        if item is not None and not isinstance(item, str | int | float):
            raise ValidationError("invalid pagination cursor")

    return tuple(decoded)


def paginate[T](
    rows: Sequence[T],
    *,
    limit: int,
    cursor_key: Callable[[T], Sequence[CursorValue]],
) -> Page[T]:
    """Build a `Page` from rows already fetched with `limit + 1`, sorted ascending by the same
    compound key `cursor_key` extracts.

    Fetching one extra row is what makes `has_more` free: if the `limit + 1`-th row came back,
    another page exists and its cursor is the compound key of the last row *kept* on this page —
    no second `COUNT` query, and no risk of an off-by-one from re-deriving "more" a different way.
    """
    if len(rows) > limit:
        page_items = tuple(rows[:limit])
        next_cursor = encode_cursor(*cursor_key(page_items[-1]))
    else:
        page_items = tuple(rows)
        next_cursor = None
    return Page(items=page_items, next_cursor=next_cursor)
