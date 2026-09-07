import { loadStripe } from '@stripe/stripe-js'
import { apiClient } from './apiClient.js'

// Stripe.js singleton, shared across any feature that needs it (fees' card element today;
// onboarding's KYC step has its own copy of this same pattern in useKycSession.js). Lives in
// services/ rather than a feature's api/ module so no feature has to import another feature's API
// client just to read a provider config value (frontend/CLAUDE.md: promote to a global folder
// only once a second feature needs it — this is that second feature).
let stripePromise = null

/**
 * Resolves to a ready Stripe.js instance, fetching the publishable key from
 * `GET /api/v1/identity/config` (public, not customer-scoped) on first call. Only the *resolved*
 * promise is cached — a rejection clears it, so a transient failure (e.g. `STRIPE_PUBLISHABLE_KEY`
 * unset server-side, which makes `/identity/config` 500) doesn't poison every later attempt for
 * the life of the tab.
 */
export function getStripe() {
  if (!stripePromise) {
    stripePromise = apiClient
      .get('/identity/config')
      .then((config) => loadStripe(config.stripe_publishable_key))
      .catch((error) => {
        stripePromise = null
        throw error
      })
  }
  return stripePromise
}
