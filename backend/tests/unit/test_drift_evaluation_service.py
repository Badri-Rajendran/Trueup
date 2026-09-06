"""S9 §9's property table for the relative drift-band comparison (S9 §4/§5): pure `Decimal` in,
`bool` out -- no database, no `Money`/`Units`/`Price` at all."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.rebalance.drift_evaluation_service import DriftEvaluationService

_BAND = Decimal("0.05")


def _flagged(current: str, target: str) -> bool:
    return DriftEvaluationService.is_out_of_band(
        current_weight_pct=Decimal(current),
        target_weight_pct=Decimal(target),
        drift_band_pct=_BAND,
    )


def test_a_holding_exactly_at_target_has_zero_drift() -> None:
    assert _flagged("0.20", "0.20") is False


@pytest.mark.parametrize(
    "current",
    [
        "0.21",  # (0.21 - 0.20) / 0.20 = +0.05 exactly
        "0.19",  # (0.19 - 0.20) / 0.20 = -0.05 exactly
    ],
)
def test_exactly_at_the_band_edge_does_not_trigger(current: str) -> None:
    """S9 §9: `== band` does not trigger."""
    assert _flagged(current, "0.20") is False


@pytest.mark.parametrize(
    "current",
    [
        "0.2101",  # relative drift = +0.0505
        "0.1899",  # relative drift = -0.0505
    ],
)
def test_just_past_the_band_edge_triggers(current: str) -> None:
    """S9 §9: `> band` triggers."""
    assert _flagged(current, "0.20") is True


def test_a_wider_target_scales_the_absolute_tolerance() -> None:
    """S9 §5: the band is relative to each holding's target weight, not a flat +/-5pp band."""
    assert _flagged("0.42", "0.40") is False  # +0.05 relative, at the edge
    assert _flagged("0.421", "0.40") is True  # past it


def test_a_zero_target_with_a_nonzero_holding_is_always_flagged() -> None:
    """S9 §8 item 4: a security dropped from the model is always flagged, a full-exit sell."""
    assert _flagged("0.0001", "0") is True


def test_a_zero_target_with_nothing_held_is_not_flagged() -> None:
    """Nothing targeted, nothing held: nothing to do."""
    assert _flagged("0", "0") is False
