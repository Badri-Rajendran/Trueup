import { useCallback, useState } from 'react'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { feesApi } from '../api/feesApi.js'

/**
 * Owns the whole tokenize-then-attach sequence (mirrors `useKycSession.js`'s ownership of both
 * the Stripe call and the API call) so the two outcomes that must always agree — "did Stripe
 * accept the card" and "did the backend save it" — live as one state machine, not two booleans a
 * component could let drift apart.
 */
export function usePaymentMethod(customerId) {
  const [status, setStatus] = useState('idle')
  const [errorMessage, setErrorMessage] = useState(null)

  const save = useCallback(
    async ({ stripe, cardElement }) => {
      setStatus('submitting')
      setErrorMessage(null)

      const { paymentMethod, error: stripeError } = await stripe.createPaymentMethod({
        type: 'card',
        card: cardElement,
      })
      if (stripeError) {
        // A declined/invalid card is an expected outcome here, not an exception — Stripe's own
        // message is already specific and customer-safe.
        setErrorMessage(stripeError.message)
        setStatus('error')
        return null
      }

      try {
        const data = await feesApi.attachPaymentMethod(customerId, paymentMethod.id)
        setStatus('submitted')
        return { brand: paymentMethod.card.brand, last4: paymentMethod.card.last4, updatedAt: data.updated_at }
      } catch (err) {
        // Today a Stripe-side decline at attach time surfaces from the backend as a generic
        // internal_error (no card_declined code exists yet — see the plan's note to flag this to
        // main as a backend follow-up); this scoped fallback is the frontend-side mitigation.
        setErrorMessage(getErrorMessage(err, "We couldn't save that card. Check the details, or try a different card."))
        setStatus('error')
        return null
      }
    },
    [customerId],
  )

  const reset = useCallback(() => {
    setStatus('idle')
    setErrorMessage(null)
  }, [])

  return { status, errorMessage, save, reset }
}
