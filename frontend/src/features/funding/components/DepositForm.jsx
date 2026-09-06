import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getFundingErrorMessage } from '../fundingErrorMessage.js'
import { useDeposit } from '../hooks/useDeposit.js'
import { parseAmount } from '../parseAmount.js'
import './FundingForm.css'

export function DepositForm({ customerId }) {
  const { status, error, deposit } = useDeposit(customerId)
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
    deposit(parsed)
      .then(() => {
        showToast({ message: 'Deposit submitted.', tone: 'success' })
        setAmount('')
      })
      .catch(() => {})
  }

  const displayError = validationMessage || (status === 'error' ? getFundingErrorMessage(error) : null)

  return (
    <form className="tu-funding-form" onSubmit={handleSubmit}>
      <Input
        label="Deposit amount"
        name="depositAmount"
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
        Deposit
      </Button>
    </form>
  )
}
