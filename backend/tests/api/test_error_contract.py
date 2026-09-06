"""The app factory renders `AppError` as RFC 9457 problem+json (S0 §8): stable `code` survives to
the client, `detail` never does.
"""

from __future__ import annotations

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError


@pytest.fixture
def raising_client(app: Flask) -> FlaskClient:
    """A client whose routes raise each error type, registered on the real factory-built app."""

    @app.get("/_test/validation")
    def _validation() -> None:
        raise ValidationError("amount must be positive")

    @app.get("/_test/forbidden")
    def _forbidden() -> None:
        raise ForbiddenError("customer 8f3a-... may not read customer 91bc-...")

    @app.get("/_test/not-found")
    def _not_found() -> None:
        raise NotFoundError()

    @app.get("/_test/conflict")
    def _conflict() -> None:
        raise ConflictError(code="idempotency_key_reused_with_different_body")

    return app.test_client()


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/_test/validation", 422, "validation_failed"),
        ("/_test/forbidden", 403, "forbidden"),
        ("/_test/not-found", 404, "not_found"),
        ("/_test/conflict", 409, "idempotency_key_reused_with_different_body"),
    ],
)
def test_app_errors_render_as_problem_json(
    raising_client: FlaskClient, path: str, status: int, code: str
) -> None:
    response = raising_client.get(path)
    assert response.status_code == status
    assert response.mimetype == "application/problem+json"
    body = response.get_json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["correlation_id"]


def test_detail_never_reaches_the_client(raising_client: FlaskClient) -> None:
    """Neither customer ID may be echoed back — that would confirm a probed identifier exists (OWASP API1)."""
    rendered = raising_client.get("/_test/forbidden").get_data(as_text=True)
    assert "8f3a" not in rendered
    assert "91bc" not in rendered
    assert "may not read" not in rendered


def test_validation_detail_never_reaches_the_client(raising_client: FlaskClient) -> None:
    rendered = raising_client.get("/_test/validation").get_data(as_text=True)
    assert "amount must be positive" not in rendered


def test_no_stack_trace_escapes(raising_client: FlaskClient) -> None:
    rendered = raising_client.get("/_test/validation").get_data(as_text=True)
    assert "Traceback" not in rendered
    assert "app/core/errors.py" not in rendered


def test_correlation_id_matches_the_response_header(raising_client: FlaskClient) -> None:
    """Support joins a customer's report to a trace through this ID; body and header must agree."""
    response = raising_client.get("/_test/not-found", headers={"X-Correlation-ID": "trace-42"})
    assert response.get_json()["correlation_id"] == "trace-42"
    assert response.headers["X-Correlation-ID"] == "trace-42"
