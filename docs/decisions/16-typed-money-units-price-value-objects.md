# 16 — Money/Units/Price value objects make dimension-mixing a type error

## Status

Accepted

## Context

The brief calls mixing units and money "the classic day-one bug" (line 42), and NFR-3 requires
dimensional safety "in storage or computation." S1 §3.3 enforces the storage half with a database
`CHECK` constraint tying each posting's non-null column to its account's declared dimension. Nothing
enforces the computation half: in Python, both `amount_money` and `quantity_units` are plain
`Decimal`, and nothing stops a service from writing `quantity_units + amount_money` — it runs
without error and produces a number that is neither a valid money nor a valid unit figure, reaching
a customer-facing screen or a tax export before any database constraint has a chance to reject it.

## Decision

Three immutable value objects in `app/core/money.py`: `Money` (`NUMERIC(18,4)`), `Units`
(`NUMERIC(28,6)`, six decimal places per FR-11), `Price` (`NUMERIC(18,6)`).

- Constructed from `str` only, never `float` — floats reintroduce binary floating-point error into a
  regulated ledger. Quantized at construction with `ROUND_HALF_EVEN`.
- `Money + Money → Money`; `Units + Units → Units`. `Money + Units`, `Money * Money`, and
  `Units * Units` all raise `TypeError`.
- Two legal cross-dimension operations, exact algebraic inverses of each other:
  `Price * Units → Money` and `Money / Units → Price` (added while implementing S0 §4; S3 §3.1's
  `average_fill_price` has no other way to be computed without dropping to a bare `Decimal`).
  `Money / Price → Units` is deliberately not implemented. The first is the direct implementation of
  FR-11's `value = units × price`.
- Comparisons are defined only between same-type instances.
- Each type has a SQLAlchemy `TypeDecorator` mapping it to its `NUMERIC` column, so an ORM attribute
  like `Posting.amount_money` is typed `Mapped[Money | None]` — a caller reading the column already
  receives a `Money`, not a bare `Decimal` whose meaning must be remembered.
- Serialized to JSON as strings (`"1500.00"`), never JSON numbers, at the API boundary — a JSON
  number is IEEE-754 and can silently lose precision in a client.

## Consequences

- NFR-3 becomes a `mypy --strict` type error and a runtime `TypeError`, not a code-review concern —
  the same shift S1 §3.3 already made at the database level, now made at the language level too.
- Every service signature that touches money or units states its dimension in its type, which is
  self-documenting and makes an accidental dimension swap visible in a diff.
- `mypy --strict` becomes a required CI gate (`docs/specs/0-backend-foundation-design.md` §11) —
  without it, this ADR's guarantee is only a runtime check exercised by whatever tests happen to hit
  the bad path, not a build-time guarantee.
- A small amount of ceremony at every arithmetic site (constructing `Money("1.00")` rather than
  writing `Decimal("1.00")` or a bare literal) — accepted as the direct cost of eliminating the
  brief's named "classic day-one bug" by construction rather than by discipline.

## Alternatives considered

- **Raw `Decimal` everywhere with naming discipline** (`amount_money`, `quantity_units`). No new
  abstraction, most familiar to any Python developer. Rejected: NFR-3 would hold only as long as
  every future change is reviewed carefully, and a wrong expression inside one service produces a
  plausible-looking `Decimal` that never reaches a database `CHECK` constraint to be caught, since
  the constraint only fires on the column a value is eventually written to — not on the arithmetic
  that produced it.
- **A `Money` value object only, `Units` left as plain `Decimal`.** Half the ceremony, and it does
  catch money-scale errors (e.g. adding a raw `Decimal` to a `Money`). Rejected because it does not
  catch the specific bug the brief names: units bleeding into a money computation would still pass
  silently as an untyped `Decimal` result.
