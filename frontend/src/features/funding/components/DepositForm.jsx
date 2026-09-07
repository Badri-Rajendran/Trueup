import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getFundingErrorMessage } from '../fundingErrorMessage.js'
import { useDeposit } from '../hooks/useDeposit.js'
import { parseAmount } from '../parseAmount.js'
import { validateDepositAmount } from '../utils/fundingSummary.js'
import { DepositLimits } from './DepositLimits.jsx'
import './FundingForm.css'

/** `bankLinkLoading` covers the short window before `FundingPage`'s `useCurrentBankLink()` call
 * resolves — the form stays enabled during that window rather than flashing a "link a bank"
 * reason that might be wrong a moment later; a submit in that window still has the server's own
 * `no_active_bank_link` response as a fallback (`fundingErrorMessage.js`). */
function disabledReasonFor(bankLink, bankLinkLoading) {
  if (bankLinkLoading) return null
  if (!bankLink) return 'Link a bank account before you can deposit.'
  if (bankLink.status === 'requires_reauth') return 'Reconnect your bank account before you can deposit.'
  return null
}

export function DepositForm({ customerId, cashSummary, bankLink, bankLinkLoading, onSubmitted }) {
  const { status, error, deposit } = useDeposit(customerId)
  const { showToast } = useToast()
  const [amount, setAmount] = useState('')
  const [validationMessage, setValidationMessage] = useState(null)

  const isSubmitting = status === 'submitting'
  const disabledReason = disabledReasonFor(bankLink, bankLinkLoading)

  const handleSubmit = (event) => {
    event.preventDefault()
    setValidationMessage(null)
    const parsed = parseAmount(amount)
    if (!parsed) {
      setValidationMessage('Enter a valid amount greater than zero.')
      return
    }
    // Pre-submit check against the real caps; the server's own cap-exceeded response
    // (getFundingErrorMessage below) stays the fallback for a race against `deposited_today`.
    const capError = validateDepositAmount(parsed, cashSummary)
    if (capError) {
      setValidationMessage(capError.message)
      return
    }
    deposit(parsed)
      .then(() => {
        showToast({ message: 'Deposit submitted.', tone: 'success' })
        setAmount('')
        onSubmitted?.()
      })
      .catch(() => {})
  }

  const displayError = validationMessage || (status === 'error' ? getFundingErrorMessage(error) : null)

  if (disabledReason) {
    return <p className="tu-funding-form__disabled-reason">{disabledReason}</p>
  }

  return (
    <form className="tu-funding-form" onSubmit={handleSubmit}>
      <Input
        label="Deposit amount"
        name="depositAmount"
        inputMode="decimal"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        placeholder="0.00"
        error={displayError}
        required
      />
      <DepositLimits cashSummary={cashSummary} />
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Deposit
      </Button>
    </form>
  )
}
