import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { usePaymentMethod } from '../hooks/usePaymentMethod.js'
import './PaymentMethodForm.css'

// MOCK — no real Stripe Billing/Elements wiring exists yet for fees (S10). A brand/last-4 pair
// stands in for a captured card rather than a fake Elements-styled form implying real capture.
export function PaymentMethodForm({ currentPaymentMethod, onAttached }) {
  const { status, error, attach } = usePaymentMethod()
  const { showToast } = useToast()
  const [brand, setBrand] = useState('Visa')
  const [last4, setLast4] = useState('')
  const [validationMessage, setValidationMessage] = useState(null)

  const isSubmitting = status === 'submitting'

  const handleSubmit = (event) => {
    event.preventDefault()
    setValidationMessage(null)
    if (!/^\d{4}$/.test(last4)) {
      setValidationMessage('Enter the last 4 digits of the card.')
      return
    }
    attach({ brand, last4 })
      .then(() => {
        showToast({ message: 'Payment method saved.', tone: 'success' })
        onAttached?.()
      })
      .catch(() => {})
  }

  const displayError = validationMessage || (status === 'error' ? getErrorMessage(error) : null)

  return (
    <form className="tu-payment-method-form" onSubmit={handleSubmit}>
      {currentPaymentMethod && (
        <p className="tu-payment-method-form__current">
          Current: {currentPaymentMethod.brand} ending in {currentPaymentMethod.last4}
        </p>
      )}
      <Input label="Card brand" name="brand" value={brand} onChange={(event) => setBrand(event.target.value)} required />
      <Input
        label="Last 4 digits"
        name="last4"
        inputMode="numeric"
        maxLength={4}
        value={last4}
        onChange={(event) => setLast4(event.target.value)}
        required
      />
      {displayError && (
        <p className="tu-payment-method-form__error" role="alert">
          {displayError}
        </p>
      )}
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Save payment method
      </Button>
    </form>
  )
}
