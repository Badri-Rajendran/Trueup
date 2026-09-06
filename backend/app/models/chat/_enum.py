"""Maps a `StrEnum` to its Postgres native enum, storing `.value` not `.name`.

Duplicated from `app.models.ledger._enum` so `app/models/chat/` has no ledger dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from enum import StrEnum


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]
