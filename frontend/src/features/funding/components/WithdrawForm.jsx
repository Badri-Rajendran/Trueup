import Decimal from 'decimal.js'
import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getFundingErrorMessage } from '../fundingErrorMessage.js'
import { useWithdraw } from '../hooks/useWithdraw.js'
import { parseAmount } from '../parseAmount.js'
import { validateWithdrawalAmount } from '../utils/fundingSummary.js'
import { CashSummary } from './CashSummary.jsx'
import './FundingForm.css'

/** See `DepositForm.jsx`'s `disabledReasonFor` for why `bankLinkLoading` short-circuits to "not
 * disabled yet" rather than guessing. A withdrawable balance of exactly zero gets its own stated
 * reason rather than letting the submit round-trip just to fail. */
function disabledReasonFor(bankLink, bankLinkLoading, cashSummary) {
  if (bankLinkLoading) return null
  if (!bankLink) return 'Link a bank account before you can withdraw.'
  if (bankLink.status === 'requires_reauth') return 'Reconnect your bank account before you can withdraw.'
  if (new Decimal(cashSummary.withdrawable).isZero()) return 'You have no withdrawable cash right now.'
  return null
}

export function WithdrawForm({ customerId, cashSummary, bankLink, bankLinkLoading, onSubmitted }) {
  const { status, error, withdraw } = useWithdraw(customerId)
  const { showToast } = useToast()
  const [amount, setAmount] = useState('')
  const [validationMessage, setValidationMessage] = useState(null)

  const isSubmitting = status === 'submitting'
  const disabledReason = disabledReasonFor(bankLink, bankLinkLoading, cashSummary)

  const handleSubmit = (event) => {
    event.preventDefault()
    setValidationMessage(null)
    const parsed = parseAmount(amount)
    if (!parsed) {
      setValidationMessage('Enter a valid amount greater than zero.')
      return
    }
    // Validates against withdrawable only, never investable (ADR 5) — the server's own
    // insufficient_withdrawable_cash response stays the fallback for a race.
    const cashError = validateWithdrawalAmount(parsed, cashSummary)
    if (cashError) {
      setValidationMessage(cashError.message)
      return
    }
    withdraw(parsed)
      .then(() => {
        showToast({ message: 'Withdrawal submitted.', tone: 'success' })
        setAmount('')
        onSubmitted?.()
      })
      .catch(() => {})
  }

  const displayError = validationMessage || (status === 'error' ? getFundingErrorMessage(error) : null)

  if (disabledReason) {
    return (
      <div className="tu-funding-form">
        <CashSummary cashSummary={cashSummary} emphasize="withdrawable" />
        <p className="tu-funding-form__disabled-reason">{disabledReason}</p>
      </div>
    )
  }

  return (
    <form className="tu-funding-form" onSubmit={handleSubmit}>
      <CashSummary cashSummary={cashSummary} emphasize="withdrawable" />
      <Input
        label="Withdrawal amount"
        name="withdrawAmount"
        inputMode="decimal"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        placeholder="0.00"
        error={displayError}
        required
      />
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Withdraw
      </Button>
    </form>
  )
}
