"""Funding routes (S2 §6): link a bank account, deposit, withdraw. All four customer routes in
this spec require an authenticated principal owning (or authorized staff for) the named
`customer_id`.

**`current_user.id` is never read directly** -- a foundation bug (escalated to `main`, not this
sub-project's file to fix; `app/controllers/api/valuation.py`'s `_resolve_customer_id` documents
it first): `load_user()` (`app/controllers/api/auth.py`) returns its principal from inside a
`UnitOfWork` that is never committed, so `UnitOfWork.__exit__` rolls back before closing --
rollback expires every loaded attribute, and the subsequent close detaches the instance, so any
later access to a *mapped* attribute (`current_user.id`) raises `DetachedInstanceError` on
literally every authenticated request. This is also why `@requires_ownership`
(`app/core/security.py`) is not used here -- it reads `current_user.id` directly.
`_authorize_customer_id` below reads the same value flask-login itself already stored in the
session cookie at login time instead, matching `valuation.py`'s own workaround.

`POST /deposits`/`POST /withdrawals` require an `Idempotency-Key` header (S0 §8, NFR-14): the key,
the SHA-256 of the exact request body, and the resulting response are stored in the same
`FundingUnitOfWork` transaction as the operation they guard (`.idempotency_keys`,
`app/services/identity/funding_uow.py`), so a replayed request returns the original response
without posting a second journal entry, and a reused key with a changed body is rejected with 409.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, UnauthenticatedError, ValidationError
from app.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyRecord,
    request_hash,
    resolve_replay,
)
from app.core.money import Money  # noqa: TC001 -- Pydantic needs the real type at class-build time.
from app.core.uow import SessionRole
from app.extensions import DbRole, limiter
from app.integrations.plaid.bank_adapter import PlaidBankAdapter
from app.services.identity import deposit_service as deposit
from app.services.identity import withdrawal_service as withdrawal
from app.services.identity.bank_link_service import BankLinkService
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.identity.null_holds_provider import NullHoldsProvider
from app.services.ledger.cash_policy_service import CashPolicyService
from app.views.funding import BankLinkResponse, DepositResponse, WithdrawalResponse

funding_bp = Blueprint("funding", __name__, url_prefix="/api/v1/funding")


class LinkBankRequest(BaseModel):
    customer_id: uuid.UUID
    plaid_public_token: str


class DepositRequest(BaseModel):
    customer_id: uuid.UUID
    amount: Money


class WithdrawalRequest(BaseModel):
    customer_id: uuid.UUID
    amount: Money


def _authorize_customer_id(target_customer_id: uuid.UUID) -> None:
    """`@login_required` + `@requires_ownership('customer_id')`'s effect, without the
    `current_user.id` access that decorator makes (see module docstring)."""
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role == "customer":
        raw_user_id = flask_session.get("_user_id")
        if not raw_user_id or uuid.UUID(raw_user_id) != target_customer_id:
            raise ForbiddenError("Cannot access resources belonging to another customer")
    elif current_user.role not in ("adviser", "admin"):
        raise ForbiddenError(f"Unknown role {current_user.role}")


def _session_role_and_customer_id(
    target_customer_id: uuid.UUID,
) -> tuple[SessionRole, uuid.UUID | None]:
    if current_user.role == "customer":
        return SessionRole.CUSTOMER, target_customer_id
    if current_user.role == "adviser":
        return SessionRole.ADVISER, None
    return SessionRole.ADMIN, None


def _plaid_adapter() -> PlaidBankAdapter:
    settings = get_settings()
    if settings.plaid_client_id is None or settings.plaid_secret is None:
        raise RuntimeError("PLAID_CLIENT_ID/PLAID_SECRET are not configured")
    return PlaidBankAdapter(
        client_id=settings.plaid_client_id.get_secret_value(),
        secret=settings.plaid_secret.get_secret_value(),
        environment=settings.plaid_env,
    )


def _save_idempotency_record(
    uow: FundingUnitOfWork,
    *,
    customer_id: uuid.UUID,
    idempotency_key: str,
    raw_body: bytes,
    body: dict[str, Any],
    status: int,
) -> None:
    uow.idempotency_keys.save(
        IdempotencyRecord(
            customer_id=customer_id,
            key=idempotency_key,
            request_hash=request_hash(raw_body),
            response_status=status,
            response_body=body,
            created_at=datetime.now(UTC),
        )
    )


@funding_bp.route("/bank-links", methods=["POST"])
@limiter.limit("10 per minute")
def create_bank_link() -> Any:
    try:
        data = LinkBankRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    _authorize_customer_id(data.customer_id)

    role, uow_customer_id = _session_role_and_customer_id(data.customer_id)

    with FundingUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        service = BankLinkService(uow, bank_port=_plaid_adapter())
        link = service.create_link(data.customer_id, plaid_public_token=data.plaid_public_token)
        uow.commit()
        view = BankLinkResponse(id=link.id, status=link.status.value, linked_at=link.linked_at)

    return jsonify(view.model_dump(mode="json")), 201


@funding_bp.route("/deposits", methods=["POST"])
@limiter.limit("10 per minute")
def create_deposit() -> Any:
    raw_body = request.get_data()
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise ValidationError("Idempotency-Key header is required")

    try:
        data = DepositRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    _authorize_customer_id(data.customer_id)

    role, uow_customer_id = _session_role_and_customer_id(data.customer_id)
    settings = get_settings()

    with FundingUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        existing = uow.idempotency_keys.find(customer_id=data.customer_id, key=idempotency_key)
        if existing is not None:
            try:
                status, body = resolve_replay(existing, raw_body)
            except IdempotencyConflictError as exc:
                raise ConflictError(str(exc)) from exc
            return jsonify(body), status

        service = deposit.DepositService(
            uow,
            deposit_cap_per_transaction=settings.deposit_cap_per_transaction,
            deposit_cap_per_day=settings.deposit_cap_per_day,
        )
        try:
            result = service.initiate(data.customer_id, amount=data.amount)
        except deposit.FundingNotEligibleError as exc:
            raise ValidationError(str(exc), code=exc.reason) from exc
        except deposit.NoActiveBankLinkError as exc:
            raise ValidationError(str(exc), code="no_active_bank_link") from exc
        except deposit.BankReauthRequiredError as exc:
            raise ValidationError(str(exc), code="bank_reauth_required") from exc
        except deposit.DepositCapExceededError as exc:
            raise ValidationError(str(exc), code=f"deposit_cap_exceeded_{exc.cap}") from exc

        view = DepositResponse(
            journal_entry_id=result.journal_entry_id,
            settlement_obligation_id=result.settlement_obligation_id,
            expected_settlement_date=result.expected_settlement_date,
        )
        body = view.model_dump(mode="json")
        _save_idempotency_record(
            uow,
            customer_id=data.customer_id,
            idempotency_key=idempotency_key,
            raw_body=raw_body,
            body=body,
            status=201,
        )
        uow.commit()

    return jsonify(body), 201


@funding_bp.route("/withdrawals", methods=["POST"])
@limiter.limit("10 per minute")
def create_withdrawal() -> Any:
    raw_body = request.get_data()
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise ValidationError("Idempotency-Key header is required")

    try:
        data = WithdrawalRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    _authorize_customer_id(data.customer_id)

    role, uow_customer_id = _session_role_and_customer_id(data.customer_id)

    with FundingUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        existing = uow.idempotency_keys.find(customer_id=data.customer_id, key=idempotency_key)
        if existing is not None:
            try:
                status, body = resolve_replay(existing, raw_body)
            except IdempotencyConflictError as exc:
                raise ConflictError(str(exc)) from exc
            return jsonify(body), status

        cash_policy = CashPolicyService(uow, holds_provider=NullHoldsProvider())
        service = withdrawal.WithdrawalService(uow, cash_policy=cash_policy)
        try:
            result = service.initiate(data.customer_id, amount=data.amount)
        except withdrawal.FundingNotEligibleError as exc:
            raise ValidationError(str(exc), code=exc.reason) from exc
        except withdrawal.NoActiveBankLinkError as exc:
            raise ValidationError(str(exc), code="no_active_bank_link") from exc
        except withdrawal.BankReauthRequiredError as exc:
            raise ValidationError(str(exc), code="bank_reauth_required") from exc
        except withdrawal.InsufficientWithdrawableCashError as exc:
            raise ValidationError(str(exc), code="insufficient_withdrawable_cash") from exc

        view = WithdrawalResponse(
            journal_entry_id=result.journal_entry_id,
            destination_bank_link_id=result.destination_bank_link_id,
        )
        body = view.model_dump(mode="json")
        _save_idempotency_record(
            uow,
            customer_id=data.customer_id,
            idempotency_key=idempotency_key,
            raw_body=raw_body,
            body=body,
            status=201,
        )
        uow.commit()

    return jsonify(body), 201
