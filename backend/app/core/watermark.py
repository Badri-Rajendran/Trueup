"""Bitemporal read watermark (ADR 1, ADR 6).

Every read of the ledger answers one of two different questions, and conflating them is the
single most damaging mistake this system can make:

- **Live / as-corrected** — "what is true now, including every correction since." Screen views,
  current balances, ad-hoc queries.
- **As-published** — "what did we tell the customer at period close." Pinned to the `recorded_at`
  watermark stored with the snapshot, and it must return the same figure forever (ADR 6's
  `derive(period, recorded_at <= publish_watermark) == snapshot` invariant, which is NFR-1's
  actual tamper detector).

ADR 6: "Every consumer of 'the published figure' must be explicit about which watermark it wants,
or it will silently get the live, as-corrected figure instead — a labelling discipline that must
be enforced at the query layer, not left to callers to remember." That is why repository methods
take `as_of: Watermark` as a **required keyword-only parameter with no default**: omitting it is a
type error caught by `mypy --strict`, not a live figure quietly mislabelled as published.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Watermark:
    """The `recorded_at` ceiling a bitemporal query filters on.

    Immutable, and constructed only through `live()` or `as_published()` — the two named readings
    are the whole point, so a bare cutoff cannot be passed around without saying which it is.
    """

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
        """An as-corrected read: everything recorded up to this moment.

        The instant is captured once, at construction, rather than re-evaluated per query. Two
        reads inside one unit of work therefore see the same world — without this, a correction
        landing mid-transaction could make a balance and the postings behind it disagree.
        """
        return cls(cutoff=(now or datetime.now(UTC)).astimezone(UTC), is_live=True)

    @classmethod
    def as_published(cls, recorded_at: datetime) -> Watermark:
        """A read pinned to a publication's stored watermark (ADR 6).

        Feed this the `recorded_at` saved alongside the snapshot, never `now()`; the point is that
        the same query returns the same figure forever, however many corrections follow.
        """
        if recorded_at.tzinfo is None:
            raise ValueError("as_published requires a timezone-aware recorded_at")
        return cls(cutoff=recorded_at.astimezone(UTC), is_live=False)

    @property
    def is_as_published(self) -> bool:
        return not self.is_live

    def __str__(self) -> str:
        kind = "live" if self.is_live else "as-published"
        return f"Watermark({kind} @ {self.cutoff.isoformat()})"
