"""The one path every journal entry is written through (S1 §3.2-§3.4).

Validates the dimension and zero-sum invariants before insert; the DB trigger is the backstop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.money import Money, Units
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import date

    from app.models.ledger import LedgerUnitOfWork


@dataclass(frozen=True, slots=True)
class PostingLeg:
    """One leg of a journal entry: exactly one of `amount_money`/`quantity_units` is set (§3.3)."""

    account_id: uuid.UUID
    amount_money: Money | None = None
    quantity_units: Units | None = None


class UnbalancedEntryError(ValueError):
    """A journal entry's money legs do not sum to zero (§3.4)."""


class InvalidPostingLegError(ValueError):
    """A leg sets zero or both of `amount_money`/`quantity_units` (§3.3)."""


class PostingService:
    def __init__(self, uow: LedgerUnitOfWork) -> None:
        self._uow = uow

    def post(
        self,
        *,
        entry_type: JournalEntryType,
        effective_date: date,
        source_event_id: uuid.UUID,
        legs: Sequence[PostingLeg],
        memo: str | None = None,
    ) -> JournalEntry:
        """Write a fresh journal entry. See `correct()` for superseding an existing one."""
        return self._write(
            entry_type=entry_type,
            effective_date=effective_date,
            source_event_id=source_event_id,
            legs=legs,
            memo=memo,
            superseded_by=None,
        )

    def correct(
        self,
        *,
        original: JournalEntry,
        effective_date: date,
        source_event_id: uuid.UUID,
        legs: Sequence[PostingLeg],
        reason: str,
        memo: str | None = None,
    ) -> JournalEntry:
        """Supersede `original` with a new entry of the same `entry_type` (S1 §3.2)."""
        return self._write(
            entry_type=original.entry_type,
            effective_date=effective_date,
            source_event_id=source_event_id,
            legs=legs,
            memo=memo,
            superseded_by=original.id,
            supersedes_reason=reason,
        )

    def _write(
        self,
        *,
        entry_type: JournalEntryType,
        effective_date: date,
        source_event_id: uuid.UUID,
        legs: Sequence[PostingLeg],
        memo: str | None,
        superseded_by: uuid.UUID | None,
        supersedes_reason: str | None = None,
    ) -> JournalEntry:
        self._validate_legs(legs)

        entry = JournalEntry(
            entry_type=entry_type,
            effective_date=effective_date,
            source_event_id=source_event_id,
            memo=memo,
            superseded_by=superseded_by,
            supersedes_reason=supersedes_reason,
        )
        self._uow.journal_entries.add(entry)
        self._uow.session.flush()  # assigns entry.id for the postings below

        for leg in legs:
            self._uow.postings.add(
                Posting(
                    journal_entry_id=entry.id,
                    account_id=leg.account_id,
                    amount_money=leg.amount_money,
                    quantity_units=leg.quantity_units,
                )
            )
        return entry

    @staticmethod
    def _validate_legs(legs: Sequence[PostingLeg]) -> None:
        if not legs:
            raise InvalidPostingLegError("a journal entry requires at least one posting leg")

        total = Money("0.00")
        for leg in legs:
            has_money = leg.amount_money is not None
            has_units = leg.quantity_units is not None
            if has_money == has_units:
                raise InvalidPostingLegError(
                    f"leg on account {leg.account_id} must set exactly one of "
                    "amount_money/quantity_units"
                )
            if leg.amount_money is not None:
                total += leg.amount_money

        if total != Money("0.00"):
            raise UnbalancedEntryError(
                f"money postings sum to {total}, not zero (S1 §3.4)"
            )
