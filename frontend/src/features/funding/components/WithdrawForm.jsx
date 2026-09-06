import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { useWithdraw } from '../hooks/useWithdraw.js'
import { getFundingErrorMessage } from '../fundingErrorMessage.js'
import { parseAmount } from '../parseAmount.js'
import { CashSummary } from './CashSummary.jsx'
import './FundingForm.css'

export function WithdrawForm({ customerId }) {
  const { status, error, withdraw } = useWithdraw(customerId)
  const { showToast } = useToast()
  const [amount, setAmount] = useState('')
  const [validationMessage, setValidationMessage] = useState(null)

  const isSubmitting = status === 'submitting'

  const handleSubmit = (event) => {
    event.preventDefault()
    setValidationMessage(null)
    const parsed = parseAmount(amount)
    if (!parsed) {
      setValidationMessage('Enter a valid amount greater than zero.')
      return
    }
    withdraw(parsed)
      .then(() => {
        showToast({ message: 'Withdrawal submitted.', tone: 'success' })
        setAmount('')
      })
      .catch(() => {})
  }

  const displayError = validationMessage || (status === 'error' ? getFundingErrorMessage(error) : null)

  return (
    <form className="tu-funding-form" onSubmit={handleSubmit}>
      <CashSummary emphasize="withdrawable" />
      <Input
        label="Withdrawal amount"
        name="withdrawAmount"
        inputMode="decimal"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        placeholder="0.00"
        required
      />
      {displayError && (
        <p className="tu-funding-form__error" role="alert">
          {displayError}
        </p>
      )}
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Withdraw
      </Button>
    </form>
  )
}
