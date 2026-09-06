"""Declarative authorization decorators (S0 §7.2): `@requires_role`, `@requires_ownership`,
`@audited`. `AuditSink` inverts the dependency on `AdminAuditLog` (S0 §3), same as `core/crypto.py`'s
`Cipher`."""

from __future__ import annotations

import functools
import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from flask import request
from flask_login import current_user

from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.uow import UnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class AuditSink(Protocol):
    """Persists one `admin_audit_log` row inside the caller's `UnitOfWork` (S0 §7.2). Must stage
    via that same `uow`, never open its own transaction."""

    def record(
        self,
        uow: UnitOfWork,
        *,
        actor_id: uuid.UUID,
        action: str,
        target_customer_id: uuid.UUID | None,
        payload_hash: str,
    ) -> None: ...


_audit_sink: AuditSink | None = None


def set_audit_sink(sink: AuditSink) -> None:
    """Install the process-wide `AuditSink`. Called once during application startup."""
    global _audit_sink
    _audit_sink = sink


def reset_audit_sink() -> None:
    """Clear the installed sink. Used by tests; never called in production code."""
    global _audit_sink
    _audit_sink = None


def get_audit_sink() -> AuditSink:
    if _audit_sink is None:
        raise RuntimeError(
            "No AuditSink installed. Call set_audit_sink() during application startup before "
            "any @audited action runs."
        )
    return _audit_sink


def requires_role(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Asserts the authenticated user has one of the required roles."""

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            if not current_user.is_authenticated:
                raise UnauthenticatedError("Authentication required")
            if current_user.role not in roles:
                raise ForbiddenError(f"Role {current_user.role} not authorized for this endpoint")
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def requires_ownership(
    customer_id_param: str = "customer_id",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Asserts the target customer_id matches the authenticated customer, or the principal is staff."""

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            if not current_user.is_authenticated:
                raise UnauthenticatedError("Authentication required")

            target_id = kwargs.get(customer_id_param)
            if not target_id and request.is_json and request.json:
                target_id = request.json.get(customer_id_param)
            elif not target_id and request.form:
                target_id = request.form.get(customer_id_param)

            if not target_id:
                raise ForbiddenError("Customer ID required for ownership check")

            target_id_str = str(target_id)

            if current_user.role in ("adviser", "admin"):
                pass
            elif current_user.role == "customer":
                if str(current_user.id) != target_id_str:
                    raise ForbiddenError("Cannot access resources belonging to another customer")
            else:
                raise ForbiddenError(f"Unknown role {current_user.role}")

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def audited(
    action: str, target_customer_id_param: str = "customer_id"
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Writes to admin_audit_log inside the same UnitOfWork as the action, via the installed
    `AuditSink`. `target_customer_id` is optional — not every audited action has one (S7 §5.2)."""

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            if not current_user.is_authenticated:
                raise UnauthenticatedError("Authentication required")

            target_id = kwargs.get(target_customer_id_param)
            if target_id is None and request.is_json and request.json:
                target_id = request.json.get(target_customer_id_param)

            uow: UnitOfWork | None = kwargs.get("uow")
            if uow is None:
                for arg in args:
                    if isinstance(arg, UnitOfWork):
                        uow = arg
                        break

            if uow is None:
                raise RuntimeError(
                    "@audited requires a UnitOfWork argument to be passed to the function"
                )

            payload = ""
            if request.is_json and request.json:
                payload = json.dumps(request.json, sort_keys=True)
            payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

            get_audit_sink().record(
                uow,
                actor_id=current_user.id,
                action=action,
                target_customer_id=uuid.UUID(str(target_id)) if target_id is not None else None,
                payload_hash=payload_hash,
            )

            return f(*args, **kwargs)

        return decorated_function

    return decorator
