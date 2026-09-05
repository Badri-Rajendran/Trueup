"""Declarative base and shared metadata for every SQLAlchemy entity.

The naming convention matters more than it looks. Without it, Postgres invents constraint names
and Alembic cannot reliably drop what it created, so `downgrade` breaks — and S0 §11 makes an
`upgrade head` → `downgrade base` round-trip a CI gate. Naming every constraint deterministically
is what makes that gate passable.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Every entity in `app/models/` inherits from this, so it lands in one metadata object."""

    metadata = metadata
