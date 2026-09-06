import { loadStripe } from '@stripe/stripe-js'
import { useCallback, useState } from 'react'
import { identityApi } from '../api/identityApi.js'

// Stripe.js singleton cached at module scope.
let stripePromise = null
function getStripe(publishableKey) {
  if (!stripePromise) {
    stripePromise = loadStripe(publishableKey)
  }
  return stripePromise
}

// Stripe Identity hosted verification (ADR 9); verdict arrives later via webhook.
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
