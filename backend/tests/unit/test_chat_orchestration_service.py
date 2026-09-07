"""`_SYSTEM_PROMPT_TEMPLATE`'s static schema block (S11 §5.2) -- a tripwire, not a content pin.

The prompt embeds the exact curated-view/column list directly (rather than relying solely on the
model calling `get_database_schema` before it guesses) after live testing found the model's first
`execute_read_only_sql` attempt guessed a wrong table name almost every time. This only guards
against a future edit silently dropping a view from the list -- it does not assert wording.
"""

from __future__ import annotations

from app.models.chat.curated_views import CURATED_VIEW_NAMES
from app.services.chat.chat_orchestration_service import _SYSTEM_PROMPT_TEMPLATE


def test_prompt_names_every_curated_view() -> None:
    for view in CURATED_VIEW_NAMES:
        assert view in _SYSTEM_PROMPT_TEMPLATE, f"{view} missing from the static schema block"


def test_prompt_never_lists_customer_id_as_a_column() -> None:
    """Every view is pre-scoped (rule 7, which correctly *warns against* using customer_id) -- the
    static schema block itself must not reintroduce the exact confusion PR #26 removed from
    `describe_schema()`'s dynamic output by listing it as an available column."""
    view_bullets = _SYSTEM_PROMPT_TEMPLATE.split("\n- v_", 1)[1]
    assert "customer_id" not in view_bullets
