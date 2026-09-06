"""RFC 9457 `application/problem+json` error hierarchy (S0 §8). `to_problem()` is the only thing
that reaches a client; `detail` is server-side logging only, never rendered."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base of the problem+json hierarchy. `status`/`title`/`code` are per-class defaults, `code`
    can also be overridden per raise."""

    status: int = 500
    title: str = "Internal Server Error"
    code: str = "internal_error"
    type_uri: str = "about:blank"
    """RFC 9457 `type`; `code` is the actual machine-readable discriminant, not `type`."""

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail if detail is not None else self.title)
        self.detail = detail
        """Server-side only. Never read by `to_problem()`."""
        if code is not None:
            self.code = code

    def to_problem(self, correlation_id: str) -> dict[str, Any]:
        """The entire client-visible surface of this error."""
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
    """The request conflicts with existing state (409). Also raised for an idempotency key reused
    with a different body hash (S0 §8)."""

    status = 409
    title = "Conflict"
    code = "conflict"


class RateLimitedError(AppError):
    """The caller has exceeded a configured rate limit (429)."""

    status = 429
    title = "Too Many Requests"
    code = "rate_limited"
