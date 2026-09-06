import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Select } from '../../../components/Select'
import { useToast } from '../../../components/Toast'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { usePaymentMethod } from '../hooks/usePaymentMethod.js'
import './PaymentMethodForm.css'

// Stripe fixed test-mode PaymentMethod ids (docs.stripe.com/testing).
const TEST_PAYMENT_METHODS = {
  visa: { label: 'Visa', paymentMethodId: 'pm_card_visa', last4: '4242' },
  mastercard: { label: 'Mastercard', paymentMethodId: 'pm_card_mastercard', last4: '4444' },
  amex: { label: 'American Express', paymentMethodId: 'pm_card_amex', last4: '0005' },
  discover: { label: 'Discover', paymentMethodId: 'pm_card_discover', last4: '1117' },
}

export function PaymentMethodForm({ customerId, currentPaymentMethod, onAttached }) {
  const { status, error, attach } = usePaymentMethod(customerId)
  const { showToast } = useToast()
  const [brandKey, setBrandKey] = useState('visa')

  const isSubmitting = status === 'submitting'

  const handleSubmit = (event) => {
    event.preventDefault()
    const chosen = TEST_PAYMENT_METHODS[brandKey]
    attach(chosen.paymentMethodId)
      .then(() => {
        showToast({ message: 'Payment method saved.', tone: 'success' })
        onAttached?.({ brand: chosen.label, last4: chosen.last4 })
      })
      .catch(() => {})
  }

  const displayError = status === 'error' ? getErrorMessage(error) : null

  return (
    <form className="tu-payment-method-form" onSubmit={handleSubmit}>
      <div className="tu-payment-method-form__current">
        <p className="tu-payment-method-form__current-label">Current payment method</p>
        {currentPaymentMethod ? (
          <p className="tu-payment-method-form__current-value">
            {currentPaymentMethod.brand} ending in {currentPaymentMethod.last4}
          </p>
        ) : (
          <p className="tu-payment-method-form__current-value tu-payment-method-form__current-value--empty">
            No payment method on file yet.
          </p>
        )}
      </div>
      <div className="tu-payment-method-form__fields">
        <Select
          label="Card"
          name="brand"
          value={brandKey}
          onChange={(event) => setBrandKey(event.target.value)}
          error={displayError}
        >
          {Object.entries(TEST_PAYMENT_METHODS).map(([key, { label, last4 }]) => (
            <option key={key} value={key}>
              {label} ending in {last4} (Stripe test card)
            </option>
          ))}
        </Select>
        <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
          Save payment method
        </Button>
      </div>
    </form>
  )
}
