"""Authentication routes (S0 §7.1/§7.2): register, login, logout, staff-only MFA enroll/verify.

`register`/`login` are CSRF-exempt (no session yet to protect); every route after issues/requires
the CSRF token `login` returns.
"""

from __future__ import annotations

from typing import Any

import redis
from flask import Blueprint, current_app, jsonify, request
from flask import session as flask_session
from flask_login import LoginManager, current_user, login_user, logout_user
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, generate_csrf
from pydantic import BaseModel, EmailStr, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ConflictError, ForbiddenError, UnauthenticatedError, ValidationError
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.identity.customer import Customer
from app.models.identity.staff import Staff
from app.services.identity.auth import (
    authenticate,
    find_principal_by_id,
    generate_totp_secret,
    hash_password,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)
from app.services.identity.uow import IdentityUnitOfWork
from app.views.auth import (
    AuthResponse,
    LogoutResponse,
    MfaEnrollResponse,
    MfaPendingResponse,
    RegisterResponse,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

login_manager = LoginManager()
csrf = CSRFProtect()
server_session = Session()

_CUSTOMER_IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes (S0 §7.1)
_CUSTOMER_REMEMBER_ME_SECONDS = 2592000  # 30 days
_STAFF_IDLE_TIMEOUT_SECONDS = 900  # 15 minutes (S0 §7.2 adviser/admin hardening)


def init_auth(app: Any) -> None:
    app.config["SESSION_TYPE"] = "redis"
    # Dedicated client, not app.extensions.make_redis(): that one decodes as UTF-8, which
    # corrupts flask-session's binary (msgpack) session payload.
    app.config["SESSION_REDIS"] = redis.Redis.from_url(app.config["TRUEUP_SETTINGS"].redis_url)
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = app.config["TRUEUP_SETTINGS"].is_production
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["PERMANENT_SESSION_LIFETIME"] = _CUSTOMER_IDLE_TIMEOUT_SECONDS

    server_session.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)


@login_manager.user_loader  # type: ignore[untyped-decorator]  # flask_login ships no py.typed
def load_user(user_id: str) -> Any:
    # Runs admin-role (no current_user yet). Expunges the object before UnitOfWork's rollback
    # expires its attributes, since Flask-Login holds onto it past this `with` block.
    with IdentityUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        principal = find_principal_by_id(uow, user_id)
        if principal is not None:
            uow.session.expunge(principal)
        return principal


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember: bool = False


class VerifyRequest(BaseModel):
    code: str


class MfaEnrollRequest(BaseModel):
    """`password` is required only for the re-enroll (reset) path, to re-prove identity (F3 fix)."""

    password: str | None = None


def _regenerate_session() -> None:
    """Session-fixation defence (S0 §7.1): new session ID on privilege escalation."""
    current_app.session_interface.regenerate(flask_session)  # type: ignore[attr-defined]


@auth_bp.route("/register", methods=["POST"])
@csrf.exempt  # type: ignore[untyped-decorator]  # flask_wtf ships no py.typed
@limiter.limit("5 per minute")
def register() -> Any:
    try:
        data = RegisterRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as e:
        raise ValidationError(str(e)) from e

    with IdentityUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        existing = uow.customers.get_by_email(data.email)
        if existing is not None:
            raise ValidationError("Email already registered")

        customer = Customer(email=data.email, password_hash=hash_password(data.password))
        uow.customers.add(customer)
        uow.commit()

        view = RegisterResponse.model_validate(customer)

    return jsonify(view.model_dump(mode="json")), 201


@auth_bp.route("/login", methods=["POST"])
@csrf.exempt  # type: ignore[untyped-decorator]  # flask_wtf ships no py.typed
@limiter.limit("10 per minute")
def login() -> Any:
    try:
        data = LoginRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as e:
        raise ValidationError(str(e)) from e

    with IdentityUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        principal = authenticate(uow, data.email, data.password)
        if principal is None:
            raise UnauthenticatedError("Invalid credentials")

        if isinstance(principal, Staff):
            flask_session["pending_mfa_user_id"] = str(principal.id)
            pending_view = MfaPendingResponse(status="mfa_required", csrf_token=generate_csrf())
            return jsonify(pending_view.model_dump(mode="json")), 200

        _regenerate_session()
        login_user(principal, remember=data.remember)
        flask_session.permanent = data.remember
        current_app.permanent_session_lifetime = (
            _CUSTOMER_REMEMBER_ME_SECONDS if data.remember else _CUSTOMER_IDLE_TIMEOUT_SECONDS
        )

        view = AuthResponse(
            id=principal.id,
            email=principal.email,
            role=principal.role,
            csrf_token=generate_csrf(),
        )

    return jsonify(view.model_dump(mode="json")), 200


@auth_bp.route("/session", methods=["GET"])
@limiter.limit("60 per minute")
def session_info() -> Any:
    """Session-restore for a page reload or fresh tab; returns `login`'s shape or 401."""
    if not current_user.is_authenticated:
        raise UnauthenticatedError("No authenticated session")

    user_id = flask_session.get("_user_id")
    if not user_id:  # pragma: no cover - defensive
        raise UnauthenticatedError("No authenticated session")

    with IdentityUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        principal = find_principal_by_id(uow, user_id)
        if principal is None:  # pragma: no cover - defensive
            raise UnauthenticatedError("No authenticated session")

        view = AuthResponse(
            id=principal.id,
            email=principal.email,
            role=principal.role,
            csrf_token=generate_csrf(),
        )

    return jsonify(view.model_dump(mode="json")), 200


@auth_bp.route("/logout", methods=["POST"])
def logout() -> Any:
    logout_user()
    flask_session.clear()
    view = LogoutResponse(status="logged_out")
    return jsonify(view.model_dump(mode="json")), 200


@auth_bp.route("/mfa/enroll", methods=["POST"])
@limiter.limit("10 per minute")
def mfa_enroll() -> Any:
    """F3 fix: first-time setup via `pending_mfa_user_id` (no secret yet), or reset via an
    authenticated session that re-proves the password (existing secret being replaced)."""
    try:
        data = MfaEnrollRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as e:
        raise ValidationError(str(e)) from e

    pending_user_id = flask_session.get("pending_mfa_user_id")
    is_reset = pending_user_id is None

    user_id: str
    if pending_user_id is not None:
        user_id = pending_user_id
    else:
        if not (current_user.is_authenticated and current_user.role in ("adviser", "admin")):
            raise UnauthenticatedError("No pending MFA session")
        user_id = str(current_user.id)

    with IdentityUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        staff = find_principal_by_id(uow, user_id)
        if not isinstance(staff, Staff):
            raise ForbiddenError("Only staff can enroll in MFA")

        already_enrolled = staff.totp_secret_encrypted is not None
        if is_reset:
            if data.password is None or not verify_password(staff.password_hash, data.password):
                raise ForbiddenError("password re-entry is required to replace MFA enrollment")
        elif already_enrolled:
            raise ConflictError(
                "MFA is already enrolled for this account; use /mfa/verify",
                code="mfa_already_enrolled",
            )

        secret = generate_totp_secret()
        staff.totp_secret_encrypted = secret
        uow.commit()
        email = staff.email

    view = MfaEnrollResponse(secret=secret, provisioning_uri=totp_provisioning_uri(secret, email))
    return jsonify(view.model_dump(mode="json")), 200


@auth_bp.route("/mfa/verify", methods=["POST"])
@limiter.limit("10 per minute")
def mfa_verify() -> Any:
    try:
        data = VerifyRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as e:
        raise ValidationError(str(e)) from e

    user_id = flask_session.get("pending_mfa_user_id")
    if not user_id:
        raise UnauthenticatedError("No pending MFA session")

    with IdentityUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        staff = find_principal_by_id(uow, user_id)
        if not isinstance(staff, Staff):
            raise ForbiddenError("Only staff can verify MFA")

        if not staff.totp_secret_encrypted:
            raise ForbiddenError("MFA not enrolled")

        if not verify_totp(staff.totp_secret_encrypted, data.code):
            raise UnauthenticatedError("Invalid MFA code")

        flask_session.pop("pending_mfa_user_id", None)
        _regenerate_session()
        login_user(staff)
        flask_session.permanent = True
        current_app.permanent_session_lifetime = _STAFF_IDLE_TIMEOUT_SECONDS

        view = AuthResponse(
            id=staff.id,
            email=staff.email,
            role=staff.role,
            csrf_token=generate_csrf(),
        )

    return jsonify(view.model_dump(mode="json")), 200
