"""Registers every entity on `Base.metadata` for Alembic autogenerate and `create_all()`/`drop_all()`."""

from app.models.base import Base as Base
from app.models.identity.customer import Customer as Customer
from app.models.identity.staff import Staff as Staff
from app.models.identity.staff_api_token import StaffApiToken as StaffApiToken

try:
    from app.models.ops.admin_audit_log import AdminAuditLog as AdminAuditLog
    from app.models.ops.agent_action_request import AgentActionRequest as AgentActionRequest
    from app.models.ops.idempotency_key import IdempotencyKey as IdempotencyKey
    from app.models.ops.inbound_event import InboundEvent as InboundEvent
    from app.models.ops.job_outbox import JobOutbox as JobOutbox
    from app.models.ops.job_run import JobRun as JobRun
except ImportError:
    pass

from app.models.chat.chat_message import ChatMessage as ChatMessage
from app.models.chat.chat_session import ChatSession as ChatSession
from app.models.chat.chat_tool_call import ChatToolCall as ChatToolCall
from app.models.fees.dunning_state import DunningState as DunningState
from app.models.fees.fee_accrual import FeeAccrual as FeeAccrual
from app.models.fees.fee_charge import FeeCharge as FeeCharge
from app.models.fees.fee_restatement_disclosure import (
    FeeRestatementDisclosure as FeeRestatementDisclosure,
)
from app.models.fees.high_water_mark import HighWaterMark as HighWaterMark
from app.models.fees.payment_method import PaymentMethod as PaymentMethod
from app.models.ledger.account import Account as Account
from app.models.ledger.customer_cash_lock import CustomerCashLock as CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry as JournalEntry
from app.models.ledger.posting import Posting as Posting
from app.models.ledger.settlement_obligation import SettlementObligation as SettlementObligation
from app.models.orders.approval_hold import ApprovalHold as ApprovalHold
from app.models.orders.order import Order as Order
from app.models.orders.order_event import OrderEvent as OrderEvent
