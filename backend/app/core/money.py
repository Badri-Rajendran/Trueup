"""Typed money/units/price value objects — dimension-mixing as a type error (ADR 16, S0 §4).

`Money` (`NUMERIC(18,4)`), `Units` (`NUMERIC(28,6)`, FR-11), `Price` (`NUMERIC(18,6)`): immutable,
`float`-rejecting, `ROUND_HALF_EVEN`-quantized, same-dimension arithmetic only plus FR-11's three
legal cross-dimension ops (`Price * Units -> Money`, `Money / Units -> Price`, `Money / Price ->
Units`).
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, ClassVar, Self, overload

from pydantic_core import core_schema
from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema


def _scalar_to_decimal(value: object, *, typename: str) -> Decimal:
    """Convert an `int`/`Decimal` scalar for multiplication/division. Never a `float` or `bool`."""
    if isinstance(value, bool):
        raise TypeError(f"{typename} scalar operations do not accept bool")
    if isinstance(value, float):
        raise TypeError(
            f"{typename} scalar operations do not accept float; use Decimal or int instead"
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(
        f"{typename} scalar operations require int or Decimal, got {type(value).__name__}"
    )


class _QuantizedDecimal:
    """Shared machinery for `Money`/`Units`/`Price`: parsing, quantization, and same-type ops.
    Not exported; each concrete type declares its own `_scale`/`_precision`."""

    __slots__ = ("_value",)

    _value: Decimal
    _scale: ClassVar[int]
    _precision: ClassVar[int]

    def __init__(self, value: str | int | Decimal | Self) -> None:
        if isinstance(value, bool):
            raise TypeError(f"{type(self).__name__} cannot be constructed from bool")
        if isinstance(value, float):
            raise TypeError(
                f"{type(self).__name__} cannot be constructed from float; binary floating point "
                "has no place in a regulated ledger. Use str, int, or Decimal instead."
            )
        if isinstance(value, _QuantizedDecimal):
            if type(value) is not type(self):
                raise TypeError(
                    f"cannot construct {type(self).__name__} from {type(value).__name__}"
                )
            decimal_value = value._value
        elif isinstance(value, (str, int, Decimal)):
            try:
                decimal_value = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError(f"invalid {type(self).__name__} value: {value!r}") from exc
        else:
            raise TypeError(
                f"{type(self).__name__} cannot be constructed from {type(value).__name__}"
            )

        if not decimal_value.is_finite():
            raise ValueError(f"{type(self).__name__} value must be finite, got {value!r}")

        quantized = decimal_value.quantize(self._quantum(), rounding=ROUND_HALF_EVEN)
        if quantized == 0:
            # Avoids serializing Decimal's negative zero as "-0.0000".
            quantized = quantized.copy_abs()
        self._validate_precision(quantized)
        object.__setattr__(self, "_value", quantized)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    @classmethod
    def _quantum(cls) -> Decimal:
        return Decimal(1).scaleb(-cls._scale)

    def _validate_precision(self, value: Decimal) -> None:
        integer_digits = len(str(abs(value).to_integral_value(rounding=ROUND_DOWN)))
        if integer_digits + self._scale > self._precision:
            raise ValueError(
                f"{type(self).__name__} value {value} exceeds NUMERIC({self._precision}, "
                f"{self._scale}) precision"
            )

    def _require_same_type(self, other: object) -> None:
        if type(other) is not type(self):
            raise TypeError(
                f"cannot operate on {type(self).__name__} and {type(other).__name__}"
            )

    # -- addition / subtraction -- same dimension only, enforced statically via `Self`.

    def __add__(self, other: Self) -> Self:
        self._require_same_type(other)
        return type(self)(self._value + other._value)

    def __sub__(self, other: Self) -> Self:
        self._require_same_type(other)
        return type(self)(self._value - other._value)

    # -- unary --

    def __neg__(self) -> Self:
        return type(self)(-self._value)

    def __abs__(self) -> Self:
        return type(self)(abs(self._value))

    # -- comparisons --

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _QuantizedDecimal):
            if type(other) is not type(self):
                raise TypeError(
                    f"cannot compare {type(self).__name__} to {type(other).__name__}"
                )
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._value))

    def __lt__(self, other: Self) -> bool:
        self._require_same_type(other)
        return self._value < other._value

    def __le__(self, other: Self) -> bool:
        self._require_same_type(other)
        return self._value <= other._value

    def __gt__(self, other: Self) -> bool:
        self._require_same_type(other)
        return self._value > other._value

    def __ge__(self, other: Self) -> bool:
        self._require_same_type(other)
        return self._value >= other._value

    # -- allocation: deterministic penny residual (non-negotiable #6) --

    def allocate(self, weights: Sequence[int]) -> list[Self]:
        """Split into `len(weights)` parts, proportional to `weights`, summing exactly to `self`.
        Largest-remainder method, tie-break by ascending weight index (non-negotiable #6)."""
        if not weights:
            raise ValueError("allocate requires at least one weight")
        if any(w < 0 for w in weights):
            raise ValueError("allocate does not accept negative weights")
        total_weight = sum(weights)
        if total_weight <= 0:
            raise ValueError("allocate requires at least one positive weight")

        sign = -1 if self._value < 0 else 1
        magnitude = abs(self._value)
        quantum = self._quantum()
        total_smallest_units = int(magnitude / quantum)

        raw_shares = [
            Decimal(total_smallest_units) * Decimal(weight) / Decimal(total_weight)
            for weight in weights
        ]
        base_units = [int(raw.to_integral_value(rounding=ROUND_DOWN)) for raw in raw_shares]
        remainders = [raw - base for raw, base in zip(raw_shares, base_units, strict=True)]
        leftover = total_smallest_units - sum(base_units)

        order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
        final_units = list(base_units)
        for i in order[:leftover]:
            final_units[i] += 1

        return [type(self)(Decimal(units) * quantum * sign) for units in final_units]

    # -- string / repr --

    def __str__(self) -> str:
        return str(self._value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._value!s})"

    # -- Pydantic integration: parse from / serialize to a JSON string, never a JSON number --

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def validate(value: Any) -> _QuantizedDecimal:
            if isinstance(value, cls):
                return value
            try:
                return cls(value)
            except TypeError as exc:
                # Surface as a Pydantic ValidationError, not a raw TypeError.
                raise ValueError(str(exc)) from exc

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema(), when_used="json"
            ),
        )


class Money(_QuantizedDecimal):
    """A USD ledger amount, `NUMERIC(18,4)`."""

    _scale = 4
    _precision = 18

    def __mul__(self, other: int | Decimal) -> Self:
        return type(self)(self._value * _scalar_to_decimal(other, typename="Money"))

    def __rmul__(self, other: int | Decimal) -> Self:
        return self.__mul__(other)

    @overload
    def __truediv__(self, other: Money) -> Decimal: ...
    @overload
    def __truediv__(self, other: Units) -> Price: ...
    @overload
    def __truediv__(self, other: Price) -> Units: ...
    @overload
    def __truediv__(self, other: int | Decimal) -> Self: ...
    def __truediv__(
        self, other: Money | Units | Price | int | Decimal
    ) -> Decimal | Price | Units | Self:
        """`Money / Money` -> ratio, `Money / Units` -> `Price`, `Money / Price` -> `Units`,
        `Money / scalar` -> `Money` — FR-11's `value = units x price`, run backward (ADR 16)."""
        if isinstance(other, Money):
            if other._value == 0:
                raise ZeroDivisionError("Money division by zero Money")
            return self._value / other._value
        if isinstance(other, Units):
            if other._value == 0:
                raise ZeroDivisionError("Money division by zero Units")
            return Price(self._value / other._value)
        if isinstance(other, Price):
            if other._value == 0:
                raise ZeroDivisionError("Money division by zero Price")
            return Units(self._value / other._value)
        divisor = _scalar_to_decimal(other, typename="Money")
        if divisor == 0:
            raise ZeroDivisionError("Money division by zero")
        return type(self)(self._value / divisor)


class Units(_QuantizedDecimal):
    """A position quantity, `NUMERIC(28,6)` — six decimal places per FR-11."""

    _scale = 6
    _precision = 28

    @overload
    def __mul__(self, other: Price) -> Money: ...
    @overload
    def __mul__(self, other: int | Decimal) -> Self: ...
    def __mul__(self, other: Price | int | Decimal) -> Money | Self:
        if isinstance(other, Price):
            return Money(self._value * other._value)
        return type(self)(self._value * _scalar_to_decimal(other, typename="Units"))

    def __rmul__(self, other: int | Decimal) -> Self:
        return type(self)(self._value * _scalar_to_decimal(other, typename="Units"))

    @overload
    def __truediv__(self, other: Units) -> Decimal: ...
    @overload
    def __truediv__(self, other: int | Decimal) -> Self: ...
    def __truediv__(self, other: Units | int | Decimal) -> Decimal | Self:
        if isinstance(other, Units):
            if other._value == 0:
                raise ZeroDivisionError("Units division by zero Units")
            return self._value / other._value
        divisor = _scalar_to_decimal(other, typename="Units")
        if divisor == 0:
            raise ZeroDivisionError("Units division by zero")
        return type(self)(self._value / divisor)


class Price(_QuantizedDecimal):
    """A per-unit price, `NUMERIC(18,6)` — not itself a ledger balance."""

    _scale = 6
    _precision = 18

    @overload
    def __mul__(self, other: Units) -> Money: ...
    @overload
    def __mul__(self, other: int | Decimal) -> Self: ...
    def __mul__(self, other: Units | int | Decimal) -> Money | Self:
        if isinstance(other, Units):
            return Money(self._value * other._value)
        return type(self)(self._value * _scalar_to_decimal(other, typename="Price"))

    def __rmul__(self, other: int | Decimal) -> Self:
        return type(self)(self._value * _scalar_to_decimal(other, typename="Price"))

    @overload
    def __truediv__(self, other: Price) -> Decimal: ...
    @overload
    def __truediv__(self, other: int | Decimal) -> Self: ...
    def __truediv__(self, other: Price | int | Decimal) -> Decimal | Self:
        if isinstance(other, Price):
            if other._value == 0:
                raise ZeroDivisionError("Price division by zero Price")
            return self._value / other._value
        divisor = _scalar_to_decimal(other, typename="Price")
        if divisor == 0:
            raise ZeroDivisionError("Price division by zero")
        return type(self)(self._value / divisor)


class MoneyType(TypeDecorator[Money]):
    """Maps `Money` to `NUMERIC(18,4)`; a `Mapped[Money]` column reads back as `Money`."""

    impl = Numeric(18, 4)
    cache_ok = True

    def process_bind_param(self, value: Money | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, Money):
            raise TypeError(f"MoneyType expects a Money instance, got {type(value).__name__}")
        return value._value

    def process_result_value(self, value: Decimal | None, dialect: Any) -> Money | None:
        if value is None:
            return None
        return Money(value)


class UnitsType(TypeDecorator[Units]):
    """Maps `Units` to `NUMERIC(28,6)` (FR-11's six decimal places)."""

    impl = Numeric(28, 6)
    cache_ok = True

    def process_bind_param(self, value: Units | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, Units):
            raise TypeError(f"UnitsType expects a Units instance, got {type(value).__name__}")
        return value._value

    def process_result_value(self, value: Decimal | None, dialect: Any) -> Units | None:
        if value is None:
            return None
        return Units(value)


class PriceType(TypeDecorator[Price]):
    """Maps `Price` to `NUMERIC(18,6)`."""

    impl = Numeric(18, 6)
    cache_ok = True

    def process_bind_param(self, value: Price | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, Price):
            raise TypeError(f"PriceType expects a Price instance, got {type(value).__name__}")
        return value._value

    def process_result_value(self, value: Decimal | None, dialect: Any) -> Price | None:
        if value is None:
            return None
        return Price(value)
