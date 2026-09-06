"""Maps a `StrEnum` to its Postgres native enum, storing `.value` not `.name`.

Duplicated locally so `app/models/ledger/` has no dependency on `app/models/ops/`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from enum import StrEnum


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]
