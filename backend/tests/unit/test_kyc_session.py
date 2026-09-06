"""Pure logic: `KycSession`'s single-transition guard (S2 §3.2) -- no database.

The trigger-backed guarantee (a second transition rejected at the database too) is covered in
`tests/integration/test_kyc_session.py`, matching `settlement_obligation`'s split between an
application-level check (here) and its database backstop (there).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.identity.kyc_session import (
    KycSession,
    KycSessionAlreadyResolvedError,
    KycSessionStatus,
)


def _pending_session(**overrides: object) -> KycSession:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "customer_id": uuid.uuid4(),
        "provider_session_id": f"vs_{uuid.uuid4()}",
        "status": KycSessionStatus.PENDING,
        "attempt_number": 1,
    }
    defaults.update(overrides)
    return KycSession(**defaults)  # type: ignore[arg-type]


def test_resolve_transitions_a_pending_session_to_approved() -> None:
    from app.models.identity.kyc_session import SqlKycSessionRepository

    session = _pending_session()
    resolved_at = datetime.now(UTC)

    SqlKycSessionRepository.resolve(
        session, status=KycSessionStatus.APPROVED, resolved_at=resolved_at
    )

    assert session.status is KycSessionStatus.APPROVED
    assert session.resolved_at == resolved_at


def test_resolve_rejects_a_second_transition_on_an_already_terminal_session() -> None:
    from app.models.identity.kyc_session import SqlKycSessionRepository

    session = _pending_session(status=KycSessionStatus.REJECTED, resolved_at=datetime.now(UTC))

    with pytest.raises(KycSessionAlreadyResolvedError, match="already"):
        SqlKycSessionRepository.resolve(
            session, status=KycSessionStatus.APPROVED, resolved_at=datetime.now(UTC)
        )
