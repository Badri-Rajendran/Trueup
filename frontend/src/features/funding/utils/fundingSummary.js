import Decimal from 'decimal.js'
import { formatMoney } from '../../../utils/format.js'

// Pure helpers for the Funding page — no React, no API calls. Money fields are wire strings
// throughout (`GET /funding/cash-summary`/`GET /funding/history`, backend/app/views/funding.py) —
// arithmetic always goes through decimal.js, never native +/* on a parsed float.

/** `outstanding_receivable` is `"0.0000"`, never `null`, for a customer who's never had a deposit
 * bounce (FR-6) — a real zero check, not a falsy/presence check. */
export function hasOutstandingBalance(cashSummary) {
  return new Decimal(cashSummary.outstanding_receivable).greaterThan(0)
}

/**
 * Today's remaining deposit headroom against both caps (S2 §5.2). `dailyRemaining` is what's left
 * of the whole-day cap regardless of transaction size; `maxAllowed` is the tighter of the two caps
 * — the actual ceiling a single deposit right now can hit. `percentUsed` is a plain JS number
 * (0-100) for CSS width/threshold use, not a Money value.
 */
export function depositHeadroom(cashSummary) {
  const perTransactionCap = new Decimal(cashSummary.deposit_cap_per_transaction)
  const dailyCap = new Decimal(cashSummary.deposit_cap_per_day)
  const depositedToday = new Decimal(cashSummary.deposited_today)
  const dailyRemaining = Decimal.max(0, dailyCap.minus(depositedToday))
  const maxAllowed = Decimal.min(perTransactionCap, dailyRemaining)
  const percentUsed = dailyCap.isZero() ? 0 : Math.min(100, depositedToday.div(dailyCap).times(100).toNumber())

  return {
    dailyRemaining: dailyRemaining.toFixed(2),
    perTransactionCap: perTransactionCap.toFixed(2),
    maxAllowed: maxAllowed.toFixed(2),
    percentUsed,
    // >= 80% of the daily cap, mirroring BillingPeriodProgress's own escalation threshold.
    isNearLimit: percentUsed >= 80,
    hasUsedToday: depositedToday.greaterThan(0),
  }
}

/** Pre-submit client-side check against the real caps (S2 §5.2) — the server's own
 * `deposit_cap_exceeded_per_transaction`/`_per_day` response (fundingErrorMessage.js) stays the
 * fallback source of truth for a race (the cap changing, or `deposited_today` moving between page
 * load and submit). `parsedAmount` is already a 2dp Money string from `parseAmount`. */
export function validateDepositAmount(parsedAmount, cashSummary) {
  const amount = new Decimal(parsedAmount)
  const perTransactionCap = new Decimal(cashSummary.deposit_cap_per_transaction)
  if (amount.greaterThan(perTransactionCap)) {
    return {
      code: 'deposit_cap_exceeded_per_transaction',
      message: `That's more than the ${formatMoney(perTransactionCap)} per-deposit limit.`,
    }
  }

  const { dailyRemaining } = depositHeadroom(cashSummary)
  if (amount.greaterThan(dailyRemaining)) {
    return {
      code: 'deposit_cap_exceeded_per_day',
      message: `That would put you over today's deposit limit — you have ${formatMoney(dailyRemaining)} left today.`,
    }
  }

  return null
}

/** Validates against `withdrawable` only, never `investable` (ADR 5) — mixing the two is a
 * regulatory-grade bug in this codebase, not a cosmetic one. */
export function validateWithdrawalAmount(parsedAmount, cashSummary) {
  const amount = new Decimal(parsedAmount)
  const withdrawable = new Decimal(cashSummary.withdrawable)
  if (amount.greaterThan(withdrawable)) {
    return {
      code: 'insufficient_withdrawable_cash',
      message: `That's more than your withdrawable cash of ${formatMoney(withdrawable)}.`,
    }
  }

  return null
}

const DEPOSIT_SETTLEMENT_DISPLAY = {
  // Neutral, not warning: pending is the normal first-48-hours state of every deposit, not a
  // problem in progress (design-system §8.3/§8.8's "disclosure, not a warning" precedent).
  pending: { label: 'Pending', tone: 'neutral', icon: 'history' },
  confirmed: { label: 'Settled', tone: 'success', icon: 'check-circle' },
  failed: { label: 'Returned', tone: 'error', icon: 'alert-circle' },
}

/** A withdrawal carries no settlement obligation of its own (`settlement_status` is always `null`
 * for one — views/funding.py's own note) — that's read as "Sent", never a fabricated status, and
 * stays neutral rather than borrowing a deposit's semantic-color meaning. */
export function settlementDisplay(entry) {
  if (entry.entry_type === 'withdrawal') {
    return { label: 'Sent', tone: 'neutral', icon: null }
  }
  return DEPOSIT_SETTLEMENT_DISPLAY[entry.settlement_status] ?? DEPOSIT_SETTLEMENT_DISPLAY.pending
}

const FAILURE_REASON_LABELS = {
  // The one reason code the simulated ACH-return job actually produces (deposit_service.py).
  ach_return: 'Returned by your bank (ACH return)',
}

/** Never renders a raw snake_case code — a known code gets real copy, an unrecognized one still
 * gets humanized (underscores to spaces, capitalized) rather than shown verbatim. */
export function formatFailureReason(reason) {
  if (!reason) return null
  if (FAILURE_REASON_LABELS[reason]) return FAILURE_REASON_LABELS[reason]
  const humanized = reason.replace(/_/g, ' ')
  return humanized.charAt(0).toUpperCase() + humanized.slice(1)
}

export function hasFundingActivity(entries) {
  return entries.length > 0
}
