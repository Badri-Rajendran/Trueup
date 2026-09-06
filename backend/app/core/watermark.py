"""Bitemporal read watermark (ADR 1, ADR 6). Distinguishes "live/as-corrected" from "as-published"
reads; repository methods take `as_of: Watermark` as required keyword-only with no default, so
omitting it is a `mypy --strict` type error, not a mislabelled live figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Watermark:
    """The `recorded_at` ceiling a bitemporal query filters on. Immutable, constructed only
    through `live()` or `as_published()`."""

    cutoff: datetime
    """Inclusive upper bound: rows with `recorded_at <= cutoff` are visible. Always tz-aware UTC."""

    is_live: bool
    """True for an as-corrected read, False for a figure pinned to a publication."""

    def __post_init__(self) -> None:
        if self.cutoff.tzinfo is None:
            raise ValueError(
                "Watermark.cutoff must be timezone-aware. A naive datetime silently assumes the "
                "server's local zone, which is exactly the day-boundary bug ADR 12 exists to "
                "prevent."
            )

    @classmethod
    def live(cls, *, now: datetime | None = None) -> Watermark:
        """An as-corrected read: everything recorded up to this moment, captured once at construction."""
        return cls(cutoff=(now or datetime.now(UTC)).astimezone(UTC), is_live=True)

    @classmethod
    def as_published(cls, recorded_at: datetime) -> Watermark:
        """A read pinned to a publication's stored watermark (ADR 6); feed it `recorded_at`, never `now()`."""
        if recorded_at.tzinfo is None:
            raise ValueError("as_published requires a timezone-aware recorded_at")
        return cls(cutoff=recorded_at.astimezone(UTC), is_live=False)

    @property
    def is_as_published(self) -> bool:
        return not self.is_live

    def __str__(self) -> str:
        kind = "live" if self.is_live else "as-published"
        return f"Watermark({kind} @ {self.cutoff.isoformat()})"
