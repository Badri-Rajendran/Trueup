"""Shared helper for mapping a `StrEnum` to its Postgres native enum, storing `.value` rather than
SQLAlchemy's default of `.name` -- matching `app.models.ledger._enum`/`app.models.orders._enum`.
Duplicated locally (rather than imported cross-domain) so `app/models/fees/` has no dependency on
another domain's `models/` package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from enum import StrEnum


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]
