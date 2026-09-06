"""Shared helper for mapping a `StrEnum` to its Postgres native enum, storing `.value` rather
than SQLAlchemy's default of `.name` -- matching `app.models.ledger._enum.enum_values`.
Duplicated locally so `app/models/chat/` has no dependency on `app/models/ledger/`, the same
reasoning `app/models/restatement/_enum.py`'s own docstring gives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from enum import StrEnum


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]
