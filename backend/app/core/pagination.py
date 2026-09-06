"""Cursor-based pagination (S0 §8). Avoids `OFFSET` skip/duplicate bugs on an append-only ledger —
a cursor names the last row seen by a compound, unique sort key (e.g. `(timestamp, id)`), opaque to
the client and tamper-evident via checksum."""

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
"""Enforced on every list endpoint (OWASP API4 — unrestricted resource consumption)."""

_MAX_CURSOR_LENGTH = 2048
"""Rejects an oversized token before it is parsed."""

_CHECKSUM_BYTES = 16


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of a cursor-paginated list. `has_more` is derived from `next_cursor`, never stored
    separately."""

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
    """Validate a client-supplied page size, or apply the default. Rejects rather than clamps."""
    if limit is None:
        return default
    if limit <= 0:
        raise ValidationError("limit must be a positive integer")
    if limit > maximum:
        raise ValidationError(f"limit must not exceed {maximum}")
    return limit


def encode_cursor(*values: CursorValue) -> str:
    """Encode a compound sort key into an opaque, tamper-evident cursor, e.g.
    `encode_cursor(posting.recorded_at.isoformat(), posting.id)`."""
    if not values:
        raise ValueError("encode_cursor requires at least one sort-key value")
    payload = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    checksum = hashlib.sha256(payload).digest()[:_CHECKSUM_BYTES]
    return base64.urlsafe_b64encode(payload + checksum).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[CursorValue, ...]:
    """Decode and verify a cursor produced by `encode_cursor`. Never raises anything but
    `ValidationError`; never echoes the offending input back."""
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
    compound key `cursor_key` extracts. The extra row is what makes `has_more` free — no `COUNT`."""
    if len(rows) > limit:
        page_items = tuple(rows[:limit])
        next_cursor = encode_cursor(*cursor_key(page_items[-1]))
    else:
        page_items = tuple(rows)
        next_cursor = None
    return Page(items=page_items, next_cursor=next_cursor)
