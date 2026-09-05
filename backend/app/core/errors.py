"""RFC 9457 `application/problem+json` error hierarchy (S0 §8).

Every route in the system eventually fails one of a handful of ways — bad input, a missing or
forbidden resource, an authentication gap, a conflicting write, too many requests. `AppError` gives
each of those one shape a frontend can branch on: a stable `code`, never a message a future
copy-edit could quietly change.

`to_problem()` is deliberately the *only* thing that reaches a client. `AppError.detail` exists
purely for server-side logging — a SQL fragment, an internal ID, a token, whatever a caller
attaches to explain what went wrong internally — and must never be threaded into the response body.
The application's error handler (`app/__init__.py`) logs `detail` and renders `to_problem()`; this
module does not wire itself into Flask, so a route or job can raise `AppError` before any web
framework is involved.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base of the problem+json hierarchy. Constructors never require `code`.

    `status`, `title`, and `code` are per-class defaults a subclass overrides; `code` can also be
    overridden per raise (`ValidationError(code="insufficient_investable_cash")`) so a later wave
    can mint a stable, domain-specific branch code without a new class for every one.
    """

    status: int = 500
    title: str = "Internal Server Error"
    code: str = "internal_error"
    type_uri: str = "about:blank"
    """RFC 9457 `type`. "about:blank" (no more specific URI minted yet) means `title` documents
    the problem type, which is exactly S0 §8's model — `code` is the actual machine-readable
    discriminant, not `type`."""

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail if detail is not None else self.title)
        self.detail = detail
        """Server-side only. Never read by `to_problem()`; log it explicitly if it helps triage."""
        if code is not None:
            self.code = code

    def to_problem(self, correlation_id: str) -> dict[str, Any]:
        """The entire client-visible surface of this error. No other attribute is ever exposed."""
        return {
            "type": self.type_uri,
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "correlation_id": correlation_id,
        }


class ValidationError(AppError):
    """Request failed input validation (422)."""

    status = 422
    title = "Unprocessable Entity"
    code = "validation_failed"


class NotFoundError(AppError):
    """The requested resource does not exist, or does not exist for this tenant (404)."""

    status = 404
    title = "Not Found"
    code = "not_found"


class ForbiddenError(AppError):
    """Authenticated, but not authorized for this resource or action (403)."""

    status = 403
    title = "Forbidden"
    code = "forbidden"


class UnauthenticatedError(AppError):
    """No valid session/credential presented (401)."""

    status = 401
    title = "Unauthorized"
    code = "unauthenticated"


class ConflictError(AppError):
    """The request conflicts with existing state (409).

    S0 §8's idempotency rule: a repeated `Idempotency-Key` whose body hash does not match the
    original request is rejected with this, rather than silently replaying or overwriting.
    """

    status = 409
    title = "Conflict"
    code = "conflict"


class RateLimitedError(AppError):
    """The caller has exceeded a configured rate limit (429)."""

    status = 429
    title = "Too Many Requests"
    code = "rate_limited"
