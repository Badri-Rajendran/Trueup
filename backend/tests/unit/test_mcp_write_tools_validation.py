"""Argument validation for S13's write tools -- pure functions, no database or MCP transport."""

from __future__ import annotations

import pytest

from app.mcp.write_tools import _parse_uuid, _require_text


def test_parse_uuid_accepts_a_well_formed_uuid() -> None:
    parsed = _parse_uuid("123e4567-e89b-12d3-a456-426614174000", field="customer_id")

    assert str(parsed) == "123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.parametrize("malformed", ["not-a-uuid", "", "12345", "  "])
def test_parse_uuid_rejects_a_malformed_value(malformed: str) -> None:
    with pytest.raises(ValueError, match="customer_id must be a valid UUID"):
        _parse_uuid(malformed, field="customer_id")


def test_require_text_accepts_non_empty_text() -> None:
    assert _require_text("a real reason", field="reason") == "a real reason"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_require_text_rejects_blank_text(blank: str) -> None:
    with pytest.raises(ValueError, match="reason is required"):
        _require_text(blank, field="reason")
