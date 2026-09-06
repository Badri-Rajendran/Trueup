"""Money/Units/Price value objects (ADR 16, S0 §4): dimension-mixing as a type error, not a habit.

The four things a regulated ledger cannot tolerate, each pinned by a test group below: a float
reaching a money computation, two dimensions being added together, a JSON number silently losing
precision, and a pro-rata split whose parts do not sum back to the whole.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from app.core.money import Money, MoneyType, Price, PriceType, Units, UnitsType

# --- construction -----------------------------------------------------------------------------


def test_money_from_str() -> None:
    assert str(Money("1500.00")) == "1500.0000"


def test_money_from_int() -> None:
    assert str(Money(1500)) == "1500.0000"


def test_money_from_decimal() -> None:
    assert str(Money(Decimal("1500.00"))) == "1500.0000"


def test_money_from_same_type_instance_copies() -> None:
    original = Money("42.00")
    assert Money(original) == original


def test_money_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Money(1500.00)  # type: ignore[arg-type]


def test_units_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Units(1.5)  # type: ignore[arg-type]


def test_price_rejects_float() -> None:
    with pytest.raises(TypeError, match="float"):
        Price(10.5)  # type: ignore[arg-type]


def test_money_rejects_bool() -> None:
    with pytest.raises(TypeError, match="bool"):
        Money(True)  # type: ignore[arg-type]


def test_money_rejects_other_dimension_instance() -> None:
    with pytest.raises(TypeError, match="Units"):
        Money(Units("1"))  # type: ignore[arg-type]


def test_money_rejects_unparseable_string() -> None:
    with pytest.raises(ValueError, match="invalid Money value"):
        Money("not-a-number")


def test_money_rejects_nan() -> None:
    with pytest.raises(ValueError, match="finite"):
        Money("NaN")


def test_money_rejects_infinity() -> None:
    with pytest.raises(ValueError, match="finite"):
        Money("Infinity")


def test_money_rejects_value_exceeding_precision() -> None:
    with pytest.raises(ValueError, match="NUMERIC"):
        Money("999999999999999.00")  # 15 integer digits + 4 scale > 18 precision


def test_units_allows_six_decimal_places() -> None:
    assert str(Units("1.123456")) == "1.123456"


# --- quantization (ROUND_HALF_EVEN) ------------------------------------------------------------


def test_quantizes_half_even_rounds_up_to_even_neighbour() -> None:
    assert str(Money("1.00015")) == "1.0002"


def test_quantizes_half_even_rounds_down_to_even_neighbour() -> None:
    assert str(Money("1.00025")) == "1.0002"


def test_quantizes_non_tie_normally() -> None:
    assert str(Money("1.00005")) == "1.0000"


def test_negative_zero_normalises_to_positive_zero() -> None:
    assert str(Money("-0.00001")) == "0.0000"


@given(st.decimals(min_value="-1e10", max_value="1e10", places=4, allow_nan=False))
def test_quantization_is_idempotent(value: Decimal) -> None:
    once = Money(value)
    twice = Money(once)
    assert once == twice
    assert str(once) == str(twice)


# --- addition / subtraction --------------------------------------------------------------------


def test_money_add_money() -> None:
    assert Money("10.00") + Money("5.00") == Money("15.00")


def test_money_sub_money() -> None:
    assert Money("10.00") - Money("5.00") == Money("5.00")


def test_units_add_units() -> None:
    assert Units("1.5") + Units("2.5") == Units("4.0")


def test_money_add_units_raises() -> None:
    with pytest.raises(TypeError):
        Money("1.00") + Units("1")  # type: ignore[operator]


def test_money_mul_money_raises() -> None:
    with pytest.raises(TypeError):
        Money("1.00") * Money("1.00")  # type: ignore[operator]


def test_units_mul_units_raises() -> None:
    with pytest.raises(TypeError):
        Units("1") * Units("1")  # type: ignore[operator]


@given(
    st.decimals(min_value="-1e6", max_value="1e6", places=4, allow_nan=False),
    st.decimals(min_value="-1e6", max_value="1e6", places=4, allow_nan=False),
)
def test_addition_is_commutative(a: Decimal, b: Decimal) -> None:
    assert Money(a) + Money(b) == Money(b) + Money(a)


@given(
    st.decimals(min_value="-1e5", max_value="1e5", places=4, allow_nan=False),
    st.decimals(min_value="-1e5", max_value="1e5", places=4, allow_nan=False),
    st.decimals(min_value="-1e5", max_value="1e5", places=4, allow_nan=False),
)
def test_addition_is_associative(a: Decimal, b: Decimal, c: Decimal) -> None:
    assert (Money(a) + Money(b)) + Money(c) == Money(a) + (Money(b) + Money(c))


# --- the one legal cross-dimension operation -----------------------------------------------


def test_price_times_units_is_money() -> None:
    result = Price("10.00") * Units("3")
    assert isinstance(result, Money)
    assert result == Money("30.00")


def test_units_times_price_is_money_and_commutative() -> None:
    assert Units("3") * Price("10.00") == Price("10.00") * Units("3")


def test_money_times_units_raises() -> None:
    with pytest.raises(TypeError):
        Money("1.00") * Units("1")  # type: ignore[operator]


def test_price_times_price_raises() -> None:
    with pytest.raises(TypeError):
        Price("1.00") * Price("1.00")  # type: ignore[operator]


# --- scalar multiplication ----------------------------------------------------------------------


def test_money_times_int_scalar() -> None:
    assert Money("10.00") * 3 == Money("30.00")


def test_int_times_money_scalar() -> None:
    assert 3 * Money("10.00") == Money("30.00")


def test_money_times_decimal_scalar() -> None:
    assert Money("10.00") * Decimal("0.5") == Money("5.00")


def test_money_times_float_scalar_raises() -> None:
    with pytest.raises(TypeError, match="float"):
        Money("10.00") * 1.5  # type: ignore[operator]


def test_money_times_bool_scalar_raises() -> None:
    with pytest.raises(TypeError, match="bool"):
        Money("10.00") * True  # type: ignore[operator]


# --- unary operators -------------------------------------------------------------------------


def test_negation() -> None:
    assert -Money("10.00") == Money("-10.00")


def test_abs() -> None:
    assert abs(Money("-10.00")) == Money("10.00")
    assert abs(Units("-1.5")) == Units("1.5")


# --- division ----------------------------------------------------------------------------------


def test_money_div_money_is_dimensionless_ratio() -> None:
    ratio = Money("10.00") / Money("4.00")
    assert isinstance(ratio, Decimal)
    assert ratio == Decimal("2.5")


def test_money_div_int_scalar() -> None:
    assert Money("10.00") / 4 == Money("2.50")


def test_money_div_by_zero_scalar_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        Money("10.00") / 0


def test_money_div_by_zero_money_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        Money("10.00") / Money("0.00")


def test_money_div_float_raises() -> None:
    with pytest.raises(TypeError, match="float"):
        Money("10.00") / 1.5  # type: ignore[operator]


def test_money_div_units_is_average_price() -> None:
    """S3 §3.1's order.average_fill_price: total notional / total units filled."""
    result = Money("1502.50") / Units("10")
    assert isinstance(result, Price)
    assert result == Price("150.25")


def test_money_div_units_pins_the_exact_rounded_result() -> None:
    """A division that does not come out even: the quantized result is pinned, not assumed."""
    assert Money("100.00") / Units("3") == Price("33.333333")


def test_money_div_units_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        Money("10.00") / Units("0")


def test_units_div_money_raises() -> None:
    """Units / Money is not a defined operation — it would be a fourth, meaningless dimension."""
    with pytest.raises(TypeError):
        Units("2") / Money("10.00")  # type: ignore[operator]


def test_money_div_units_is_statically_typed_as_price() -> None:
    """Fails `mypy --strict` if the `Money / Units` overload ever degrades to the base type."""
    result: Price = Money("1502.50") / Units("10")
    assert result == Price("150.25")


def test_money_div_price_is_order_quantity() -> None:
    """S9 §6's `RebalanceOrderService`: a dollar drift amount / the current price = the order
    quantity to close it. The algebraic inverse of `Money / Units -> Price` above."""
    result = Money("1502.50") / Price("150.25")
    assert isinstance(result, Units)
    assert result == Units("10")


def test_money_div_price_pins_the_exact_rounded_result() -> None:
    assert Money("100.00") / Price("3.00") == Units("33.333333")


def test_money_div_price_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        Money("10.00") / Price("0")


def test_price_div_money_raises() -> None:
    """Price / Money is not a defined operation — it would be a fourth, meaningless dimension."""
    with pytest.raises(TypeError):
        Price("2.00") / Money("10.00")  # type: ignore[operator]


def test_money_div_price_is_statically_typed_as_units() -> None:
    """Fails `mypy --strict` if the `Money / Price` overload ever degrades to the base type."""
    result: Units = Money("1502.50") / Price("150.25")
    assert result == Units("10")


# --- comparisons -----------------------------------------------------------------------------


def test_ordering_same_type() -> None:
    assert Money("1.00") < Money("2.00")
    assert Money("2.00") >= Money("2.00")


def test_equality_cross_dimension_raises() -> None:
    with pytest.raises(TypeError):
        _ = Money("1.00") == Units("1.00")  # type: ignore[operator]


def test_less_than_cross_dimension_raises() -> None:
    with pytest.raises(TypeError):
        _ = Money("1.00") < Units("1.00")  # type: ignore[operator]


def test_equality_to_unrelated_type_is_false_not_an_exception() -> None:
    assert (Money("1.00") == "1.00") is False
    assert (Money("1.00") == 1) is False


def test_hashable() -> None:
    values = {Money("1.00"), Units("1.00"), Money("1.00")}
    assert len(values) == 2


# --- allocate(): deterministic penny residual (non-negotiable #6) ------------------------------


def test_allocate_sums_exactly_to_original_with_residual() -> None:
    parts = Money("10.00").allocate([1, 1, 1])
    assert sum(parts[1:], parts[0]) == Money("10.00")
    assert parts == [Money("3.3334"), Money("3.3333"), Money("3.3333")]


def test_allocate_residual_goes_to_largest_remainder_first() -> None:
    parts = Money("10.00").allocate([2, 1])
    assert parts == [Money("6.6667"), Money("3.3333")]
    assert parts[0] + parts[1] == Money("10.00")


def test_allocate_is_deterministic_across_repeated_calls() -> None:
    total = Money("100.00")
    assert total.allocate([1, 1, 1]) == total.allocate([1, 1, 1])


def test_allocate_preserves_sign() -> None:
    parts = Money("-10.00").allocate([1, 1, 1])
    assert sum(parts[1:], parts[0]) == Money("-10.00")


def test_allocate_rejects_empty_weights() -> None:
    with pytest.raises(ValueError, match="weight"):
        Money("10.00").allocate([])


def test_allocate_rejects_all_zero_weights() -> None:
    with pytest.raises(ValueError, match="weight"):
        Money("10.00").allocate([0, 0])


def test_allocate_rejects_negative_weights() -> None:
    with pytest.raises(ValueError, match="negative"):
        Money("10.00").allocate([1, -1])


def test_units_allocate_uses_six_place_scale() -> None:
    parts = Units("1").allocate([1, 1, 1])
    assert sum(parts[1:], parts[0]) == Units("1")


# --- JSON / Pydantic ---------------------------------------------------------------------------


class _Posting(BaseModel):
    amount: Money
    quantity: Units
    price: Price


def test_pydantic_round_trip_via_json() -> None:
    posting = _Posting(amount=Money("1500.00"), quantity=Units("3.5"), price=Price("428.5714"))
    dumped = posting.model_dump_json()
    assert '"1500.0000"' in dumped
    restored = _Posting.model_validate_json(dumped)
    assert restored == posting


def test_pydantic_serializes_as_json_string_never_a_number() -> None:
    posting = _Posting(amount=Money("1500.00"), quantity=Units("1"), price=Price("1"))
    payload = posting.model_dump(mode="json")
    assert payload["amount"] == "1500.0000"
    assert isinstance(payload["amount"], str)


def test_pydantic_parses_from_string() -> None:
    posting = _Posting.model_validate(
        {"amount": "1500.00", "quantity": "3.5", "price": "428.5714"}
    )
    assert posting.amount == Money("1500.00")


def test_pydantic_rejects_float_input_as_validation_error() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _Posting.model_validate({"amount": 1500.00, "quantity": "1", "price": "1"})


# --- SQLAlchemy TypeDecorators -------------------------------------------------------------------


def test_money_type_round_trip() -> None:
    column = MoneyType()
    bound = column.process_bind_param(Money("1500.00"), None)  # type: ignore[arg-type]
    assert bound == Decimal("1500.0000")
    result = column.process_result_value(bound, None)  # type: ignore[arg-type]
    assert result == Money("1500.00")
    assert isinstance(result, Money)


def test_money_type_none_passes_through() -> None:
    column = MoneyType()
    assert column.process_bind_param(None, None) is None  # type: ignore[arg-type]
    assert column.process_result_value(None, None) is None  # type: ignore[arg-type]


def test_units_type_round_trip() -> None:
    column = UnitsType()
    bound = column.process_bind_param(Units("3.5"), None)  # type: ignore[arg-type]
    result = column.process_result_value(bound, None)  # type: ignore[arg-type]
    assert result == Units("3.5")


def test_price_type_round_trip() -> None:
    column = PriceType()
    bound = column.process_bind_param(Price("428.5714"), None)  # type: ignore[arg-type]
    result = column.process_result_value(bound, None)  # type: ignore[arg-type]
    assert result == Price("428.5714")


def test_money_type_rejects_wrong_type() -> None:
    column = MoneyType()
    with pytest.raises(TypeError):
        column.process_bind_param(Units("1"), None)  # type: ignore[arg-type]
