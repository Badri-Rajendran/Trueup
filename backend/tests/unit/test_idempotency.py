from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyRecord,
    request_hash,
    resolve_replay,
)


def test_request_hash_is_stable_for_the_exact_request_body() -> None:
    assert request_hash(b'{"amount":"10.00"}') == request_hash(b'{"amount":"10.00"}')
    assert request_hash(b'{"amount":"10.00"}') != request_hash(b'{"amount":"11.00"}')


def test_matching_key_and_body_replays_the_original_response() -> None:
    body = b'{"amount":"10.00"}'
    record = IdempotencyRecord(
        customer_id=uuid.uuid4(),
        key="deposit-1",
        request_hash=request_hash(body),
        response_status=201,
        response_body={"id": "deposit-1"},
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )

    assert resolve_replay(record, body) == (201, {"id": "deposit-1"})


def test_reused_key_with_different_body_is_rejected() -> None:
    record = IdempotencyRecord(
        customer_id=uuid.uuid4(),
        key="deposit-1",
        request_hash=request_hash(b'{"amount":"10.00"}'),
        response_status=201,
        response_body={"id": "deposit-1"},
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )

    with pytest.raises(IdempotencyConflictError):
        resolve_replay(record, b'{"amount":"11.00"}')
