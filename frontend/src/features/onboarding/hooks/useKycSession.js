import { loadStripe } from '@stripe/stripe-js'
import { useCallback, useState } from 'react'
import { identityApi } from '../api/identityApi.js'

// The publishable key never changes within a running app, so the Stripe.js singleton is cached
// at module scope rather than re-fetched/reloaded on every verification attempt.
let stripePromise = null
function getStripe(publishableKey) {
  if (!stripePromise) {
    stripePromise = loadStripe(publishableKey)
  }
  return stripePromise
}

/**
 * `POST /identity/kyc-sessions` + Stripe Identity's own hosted verification modal
 * (`stripe.verifyIdentity`, ADR 9). Resolving here means the customer finished the modal flow —
 * the actual verdict (pending → approved/rejected) arrives later via Stripe's webhook, so callers
 * should refetch `useIdentityStatus` rather than assume approval.
 */
export function useKycSession() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const startVerification = useCallback(async (customerId) => {
    setStatus('submitting')
    setError(null)
    try {
      const [session, config] = await Promise.all([
        identityApi.startKycSession(customerId),
        identityApi.getConfig(),
      ])
      setStatus('verifying')
      const stripe = await getStripe(config.stripe_publishable_key)
      const { error: stripeError } = await stripe.verifyIdentity(session.client_secret)
      if (stripeError) {
        throw stripeError
      }
      setStatus('completed')
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, startVerification }
}
