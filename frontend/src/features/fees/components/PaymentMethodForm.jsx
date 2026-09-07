import { useCallback, useId } from 'react'
import { Badge } from '../../../components/Badge'
import { Button } from '../../../components/Button'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { useToast } from '../../../components/Toast'
import { useStripeCardElement } from '../hooks/useStripeCardElement.js'
import { usePaymentMethod } from '../hooks/usePaymentMethod.js'
import './PaymentMethodForm.css'

const BRAND_LABELS = { visa: 'Visa', mastercard: 'Mastercard', amex: 'American Express', discover: 'Discover' }

function brandLabel(brand) {
  return BRAND_LABELS[brand] || (brand ? brand[0].toUpperCase() + brand.slice(1) : 'Card')
}

/** Real Stripe Elements card entry (client-side tokenization — Trueup never handles raw card
 * data, PCI scope stays with Stripe) via `@stripe/stripe-js` used imperatively: no
 * `@stripe/react-stripe-js` dependency, since one field doesn't need a React provider on top of
 * the vanilla API this app already depends on. */
export function PaymentMethodForm({ customerId, currentPaymentMethod, onAttached }) {
  const { status, errorMessage, save, reset } = usePaymentMethod(customerId)
  const { containerRef, status: cardStatus, cardElement, stripe, cardError, retry } = useStripeCardElement({
    onChange: reset,
  })
  const { showToast } = useToast()
  const labelId = useId()

  const isSubmitting = status === 'submitting'
  const message = errorMessage || cardError
  // `cardError` gates submission too -- Stripe's own `change` event already told us this card is
  // invalid, so there's no reason to round-trip a submit attempt that createPaymentMethod would
  // just reject a second time.
  const canSubmit = cardStatus === 'ready' && Boolean(stripe) && Boolean(cardElement) && !isSubmitting && !cardError

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault()
      if (!canSubmit) return

      const saved = await save({ stripe, cardElement })
      if (saved) {
        showToast({ message: 'Payment method saved.', tone: 'success' })
        cardElement.clear()
        onAttached?.({ brand: saved.brand, last4: saved.last4 })
      }
    },
    [canSubmit, save, stripe, cardElement, showToast, onAttached],
  )

  return (
    <form className="tu-payment-method-form" onSubmit={handleSubmit}>
      <div className="tu-payment-method-form__current">
        <div className="tu-payment-method-form__current-head">
          <span className="tu-payment-method-form__current-label">Card on file</span>
          {!currentPaymentMethod && <Badge tone="neutral">Not shown</Badge>}
        </div>
        {currentPaymentMethod ? (
          <>
            <p className="tu-payment-method-form__current-value">
              {brandLabel(currentPaymentMethod.brand)} ending in {currentPaymentMethod.last4}
            </p>
            <p className="tu-payment-method-form__current-caption">
              Saved in this session. Trueup doesn&apos;t read card details back from Stripe, so this
              reflects only the card you added here.
            </p>
          </>
        ) : (
          <>
            <p className="tu-payment-method-form__current-value tu-payment-method-form__current-value--empty">
              Trueup doesn&apos;t display saved card details.
            </p>
            <p className="tu-payment-method-form__current-caption">
              Stripe holds your card; this page can&apos;t read it back, so a card you added in an
              earlier session won&apos;t appear here. Saving a card below replaces whatever is
              currently on file.
            </p>
          </>
        )}
      </div>

      {cardStatus === 'error' ? (
        <ErrorState description="We couldn't load the secure card form." onRetry={retry} />
      ) : (
        <div className={['tu-field', message ? 'tu-field--error' : ''].filter(Boolean).join(' ')}>
          <span className="tu-field__label" id={labelId}>
            Card details
          </span>
          {cardStatus === 'loading' && <Skeleton height="40px" radius="var(--radius-sm)" />}
          <div
            className="tu-card-field__control"
            role="group"
            aria-labelledby={labelId}
            ref={containerRef}
            hidden={cardStatus === 'loading'}
          />
          {message && (
            <span className="tu-field__message" role="alert">
              {message}
            </span>
          )}
        </div>
      )}

      <Button type="submit" loading={isSubmitting} disabled={!canSubmit}>
        Save payment method
      </Button>
    </form>
  )
}
