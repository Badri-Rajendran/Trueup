"""`HighWaterMarkService.ratchet`/`get_or_create` (S10 §4, ADR 10) — pure logic, no database.

`shadow_nav` itself needs a real ledger (TWR/valuation), so it is exercised in
`tests/integration/test_fee_accrual_service.py` instead (matching `TwrService`'s own precedent of
keeping its DB-backed property tests in `tests/integration/`); this file isolates the
high-water-mark *ratchet* -- the part of S10's core correctness requirement that is pure arithmetic
over an already-known `shadow_value`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from app.core.money import Money
from app.models.fees.high_water_mark import HighWaterMark
from app.services.fees.high_water_mark_service import HighWaterMarkService

_FIXED_NOW = datetime(2026, 9, 5, tzinfo=UTC)


class _FakeHighWaterMarkRepo:
    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, HighWaterMark] = {}

    def get_by_customer(self, customer_id: uuid.UUID) -> HighWaterMark | None:
        return self._rows.get(customer_id)

    def add(self, hwm: HighWaterMark) -> None:
        self._rows[hwm.customer_id] = hwm


class _FakeSession:
    def flush(self) -> None:
        pass


class _FakeUow:
    def __init__(self) -> None:
        self.high_water_marks = _FakeHighWaterMarkRepo()
        self.session = _FakeSession()


def _service() -> HighWaterMarkService:
    return HighWaterMarkService(_FakeUow(), now=lambda: _FIXED_NOW)  # type: ignore[arg-type]


def test_get_or_create_creates_at_first_ever_value_with_zero_gain() -> None:
    """S10 §4: "creates at first-ever value if absent" -- the first day always yields zero gain,
    since nothing has ever been "above" a peak that did not exist yet."""
    service = _service()
    customer_id = uuid.uuid4()
    shadow_value = Money("10000.00")

    hwm = service.get_or_create(customer_id, shadow_value=shadow_value)
    gain = service.ratchet(hwm, shadow_value=shadow_value)

    assert hwm.peak_value == shadow_value
    assert gain == Money("0.00")


def test_ratchet_never_moves_the_peak_down() -> None:
    """The high-water-mark's entire guarantee (S10 §4/ADR 10): a drawdown never lowers the peak,
    and accrues nothing until the customer's value exceeds the *prior* peak again."""
    service = _service()
    customer_id = uuid.uuid4()
    hwm = service.get_or_create(customer_id, shadow_value=Money("10000.00"))
    service.ratchet(hwm, shadow_value=Money("10000.00"))

    # A drawdown to 8000 -- no new high, zero gain, peak stays at 10000.
    gain_in_drawdown = service.ratchet(hwm, shadow_value=Money("8000.00"))
    assert gain_in_drawdown == Money("0.00")
    assert hwm.peak_value == Money("10000.00")

    # Recovering only back to the prior peak -- still zero gain (S10 §8 edge case 1: no
    # retroactive "catch-up" on the drawdown period).
    gain_at_prior_peak = service.ratchet(hwm, shadow_value=Money("10000.00"))
    assert gain_at_prior_peak == Money("0.00")
    assert hwm.peak_value == Money("10000.00")

    # Only once the value exceeds the *prior* peak does new gain register, on the excess only.
    gain_above_peak = service.ratchet(hwm, shadow_value=Money("10500.00"))
    assert gain_above_peak == Money("500.00")
    assert hwm.peak_value == Money("10500.00")


@given(
    shadow_values=st.lists(
        st.decimals(min_value="0.01", max_value="1000000", places=2), min_size=1, max_size=25
    )
)
def test_peak_is_monotonically_non_decreasing_over_any_sequence(shadow_values: list) -> None:
    """Property: whatever sequence of shadow-NAV values arrives, `peak_value` never decreases,
    and every reported gain equals the peak's own increase that step."""
    service = _service()
    customer_id = uuid.uuid4()
    first = Money(str(shadow_values[0]))
    hwm = service.get_or_create(customer_id, shadow_value=first)

    peak_before = hwm.peak_value
    for raw in shadow_values:
        shadow_value = Money(str(raw))
        gain = service.ratchet(hwm, shadow_value=shadow_value)

        assert hwm.peak_value >= peak_before  # never decreases
        assert gain == Money("0.00") or hwm.peak_value == shadow_value
        if shadow_value > peak_before:
            assert gain == shadow_value - peak_before
        else:
            assert gain == Money("0.00")
        peak_before = hwm.peak_value
