"""RFC 9457 error hierarchy: rendered body never exceeds the declared key set (S0 §8)."""

from __future__ import annotations

import json

from app.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)

PROBLEM_KEYS = {"type", "title", "status", "code", "correlation_id"}


def test_base_error_has_a_sane_default_shape() -> None:
    problem = AppError().to_problem("cid-0")
    assert set(problem) == PROBLEM_KEYS
    assert problem["status"] == 500
    assert problem["code"] == "internal_error"


def test_validation_error_shape() -> None:
    problem = ValidationError().to_problem("cid-1")
    assert problem["status"] == 422
    assert problem["code"] == "validation_failed"


def test_not_found_error_shape() -> None:
    problem = NotFoundError().to_problem("cid-2")
    assert problem["status"] == 404
    assert problem["code"] == "not_found"


def test_forbidden_error_shape() -> None:
    problem = ForbiddenError().to_problem("cid-3")
    assert problem["status"] == 403
    assert problem["code"] == "forbidden"


def test_unauthenticated_error_shape() -> None:
    problem = UnauthenticatedError().to_problem("cid-4")
    assert problem["status"] == 401
    assert problem["code"] == "unauthenticated"


def test_conflict_error_shape() -> None:
    """Idempotency-key-with-different-body reuses this (S0 §8)."""
    problem = ConflictError().to_problem("cid-5")
    assert problem["status"] == 409
    assert problem["code"] == "conflict"


def test_rate_limited_error_shape() -> None:
    problem = RateLimitedError().to_problem("cid-6")
    assert problem["status"] == 429
    assert problem["code"] == "rate_limited"


def test_correlation_id_is_carried_through_unchanged() -> None:
    problem = NotFoundError().to_problem("11111111-1111-1111-1111-111111111111")
    assert problem["correlation_id"] == "11111111-1111-1111-1111-111111111111"


def test_code_can_be_overridden_for_a_stable_domain_code() -> None:
    """A later wave can override `code` without a new class; status/title stay 422."""
    problem = ValidationError(code="insufficient_investable_cash").to_problem("cid-7")
    assert problem["status"] == 422
    assert problem["code"] == "insufficient_investable_cash"


def test_sensitive_detail_never_leaks_into_the_rendered_problem() -> None:
    """Detail is available to logging, never returned to the client."""
    sensitive = (
        "duplicate key value violates unique constraint on customer_id=11111111-1111-1111-1111-"
        "111111111111 with plaid_access_token=access-sandbox-super-secret"
    )
    error = ConflictError(sensitive)
    assert error.detail == sensitive

    problem = error.to_problem("cid-8")
    rendered = json.dumps(problem)
    assert "customer_id" not in rendered
    assert "plaid_access_token" not in rendered
    assert "access-sandbox-super-secret" not in rendered
    assert "11111111" not in rendered
    assert set(problem) == PROBLEM_KEYS


def test_default_detail_is_the_title_not_none() -> None:
    """`NotFoundError()` with no detail still produces a sensible exception message for logs."""
    error = NotFoundError()
    assert str(error) == "Not Found"
    assert error.detail is None


def test_app_error_is_a_real_exception() -> None:
    try:
        raise ValidationError("bad input")
    except AppError as exc:
        assert isinstance(exc, Exception)
        assert exc.detail == "bad input"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected AppError to propagate as an exception")
