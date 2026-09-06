"""Watermark (ADR 1, ADR 6): a read is either live or as-published, and never ambiguous."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.watermark import Watermark

PUBLISHED_AT = datetime(2026, 8, 31, 21, 5, 0, tzinfo=UTC)


def test_live_is_flagged_live() -> None:
    watermark = Watermark.live()
    assert watermark.is_live is True
    assert watermark.is_as_published is False


def test_as_published_is_flagged_as_published() -> None:
    watermark = Watermark.as_published(PUBLISHED_AT)
    assert watermark.is_live is False
    assert watermark.is_as_published is True
    assert watermark.cutoff == PUBLISHED_AT


def test_live_captures_the_instant_once() -> None:
    """Two reads in one unit of work must see the same world."""
    watermark = Watermark.live()
    assert watermark.cutoff == watermark.cutoff


def test_live_accepts_an_injected_clock() -> None:
    fixed = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    assert Watermark.live(now=fixed).cutoff == fixed


def test_naive_datetime_is_rejected_by_as_published() -> None:
    """A naive datetime silently assumes the server's zone (ADR 12 day-boundary bug)."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Watermark.as_published(datetime(2026, 8, 31, 21, 5, 0))  # noqa: DTZ001


def test_naive_datetime_is_rejected_by_the_constructor() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Watermark(cutoff=datetime(2026, 8, 31, 21, 5, 0), is_live=True)  # noqa: DTZ001


def test_non_utc_input_is_normalised_to_utc() -> None:
    """Stored comparisons happen in UTC; normalising at the boundary keeps them comparable."""
    eastern = timezone(timedelta(hours=-4))
    watermark = Watermark.as_published(datetime(2026, 8, 31, 17, 5, 0, tzinfo=eastern))
    assert watermark.cutoff == PUBLISHED_AT
    assert watermark.cutoff.tzinfo is UTC


def test_watermark_is_immutable() -> None:
    """A watermark handed to a repository must not be mutable underneath it."""
    watermark = Watermark.as_published(PUBLISHED_AT)
    with pytest.raises(AttributeError):
        watermark.cutoff = datetime.now(UTC)  # type: ignore[misc]


def test_equality_distinguishes_live_from_as_published() -> None:
    """Same instant, different question. These must never compare equal."""
    assert Watermark.live(now=PUBLISHED_AT) != Watermark.as_published(PUBLISHED_AT)


def test_str_states_which_reading_it_is() -> None:
    assert "as-published" in str(Watermark.as_published(PUBLISHED_AT))
    assert "live" in str(Watermark.live())
