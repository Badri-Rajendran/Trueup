"""Read-only security catalogue backing `GET /api/v1/securities` (a future watchlist feature).
Not tenant-scoped -- any authenticated session sees the same active-security list.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.core.errors import ValidationError
from app.core.pagination import decode_cursor, paginate

if TYPE_CHECKING:
    from app.models.marketdata import MarketDataUnitOfWork
    from app.models.marketdata.daily_close import DailyClose
    from app.models.marketdata.security import Security


def _decode_security_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    decoded = decode_cursor(cursor)
    if len(decoded) != 2 or not isinstance(decoded[0], str) or not isinstance(decoded[1], str):
        raise ValidationError("invalid pagination cursor")
    try:
        return decoded[0], uuid.UUID(decoded[1])
    except ValueError as exc:
        raise ValidationError("invalid pagination cursor") from exc


class SecurityCatalogService:
    """Lists active securities with each one's latest close, keyset-paginated on `(symbol, id)`."""

    def __init__(self, uow: MarketDataUnitOfWork) -> None:
        self._uow = uow

    def list_active(
        self, *, limit: int, after: str | None
    ) -> tuple[list[tuple[Security, DailyClose | None, DailyClose | None]], str | None]:
        cursor = _decode_security_cursor(after) if after is not None else None
        rows = self._uow.securities.list_active(limit=limit, after=cursor)
        page = paginate(
            rows, limit=limit, cursor_key=lambda security: (security.symbol, str(security.id))
        )

        security_ids = [security.id for security in page.items]
        last_closes = self._uow.daily_closes.latest_for_securities(security_ids)
        previous_closes = self._uow.daily_closes.previous_close_for_securities(security_ids)
        paired = [
            (security, last_closes.get(security.id), previous_closes.get(security.id))
            for security in page.items
        ]
        return paired, page.next_cursor


__all__ = ["SecurityCatalogService"]
