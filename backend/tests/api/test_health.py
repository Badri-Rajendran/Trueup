"""Health endpoints (S0 §8): unauthenticated, no business data, no internal detail."""

from __future__ import annotations

from flask.testing import FlaskClient


def test_liveness_is_unauthenticated_and_cheap(client: FlaskClient) -> None:
    """Liveness answers "is this process running" — it must not touch a database."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.get_json() == {"status": "alive"}


def test_readiness_reports_dependency_status(client: FlaskClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "redis": True}


def test_readiness_leaks_no_connection_detail(client: FlaskClient) -> None:
    """An unauthenticated endpoint must not publish hostnames, ports, or driver errors."""
    rendered = client.get("/health/ready").get_data(as_text=True)
    for leak in ("localhost", "5433", "6380", "postgresql", "trueup_app", "password"):
        assert leak not in rendered.lower()


def test_health_endpoints_carry_security_headers(client: FlaskClient) -> None:
    """Talisman is applied globally, not per-blueprint (S0 §7.4, A05)."""
    headers = client.get("/health/live").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in headers


def test_unknown_route_returns_problem_json(client: FlaskClient) -> None:
    """Errors are RFC 9457 application/problem+json (S0 §8), including the framework's own."""
    response = client.get("/health/does-not-exist")
    assert response.status_code == 404
    assert response.mimetype == "application/problem+json"
    body = response.get_json()
    assert body["status"] == 404
    assert set(body) >= {"type", "title", "status", "code", "correlation_id"}


def test_error_response_carries_no_stack_trace(client: FlaskClient) -> None:
    rendered = client.get("/health/does-not-exist").get_data(as_text=True)
    assert "Traceback" not in rendered
    assert "app/" not in rendered


def test_correlation_id_is_echoed_on_every_response(client: FlaskClient) -> None:
    """NFR/A09: one correlation ID per request, usable to join logs to a customer report."""
    response = client.get("/health/live")
    assert response.headers["X-Correlation-ID"]


def test_supplied_correlation_id_is_honoured(client: FlaskClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "abc-123"})
    assert response.headers["X-Correlation-ID"] == "abc-123"
