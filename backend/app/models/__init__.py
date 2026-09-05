"""Importing this package registers every entity on `Base.metadata` — required for Alembic
autogenerate (`alembic/env.py`) and for any `Base.metadata.create_all()`/`drop_all()` call to see
the full schema. Each import below exists for that side effect; the `as X` re-export makes the
"unused import" that would otherwise be an intent, not an oversight."""

from app.models.base import Base as Base
from app.models.identity.customer import Customer as Customer
from app.models.identity.staff import Staff as Staff

try:
    from app.models.ops.admin_audit_log import AdminAuditLog as AdminAuditLog
    from app.models.ops.idempotency_key import IdempotencyKey as IdempotencyKey
    from app.models.ops.inbound_event import InboundEvent as InboundEvent
    from app.models.ops.job_outbox import JobOutbox as JobOutbox
    from app.models.ops.job_run import JobRun as JobRun
except ImportError:
    pass

from app.models.ledger.account import Account as Account
from app.models.ledger.customer_cash_lock import CustomerCashLock as CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry as JournalEntry
from app.models.ledger.posting import Posting as Posting
from app.models.ledger.settlement_obligation import SettlementObligation as SettlementObligation
