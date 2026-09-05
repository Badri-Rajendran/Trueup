import { apiClient } from '../../../services/apiClient.js'

// Bank-link exchange only (per structure.md §3) — deposits/withdrawals belong to the `funding`
// feature (Phase 2), not onboarding.
export const fundingApi = {
  // Mints the Plaid `link_token` the Plaid Link widget needs before it can even open.
  createLinkToken: (customerId) => apiClient.post('/funding/link-token', { customer_id: customerId }),
  createBankLink: (customerId, plaidPublicToken) =>
    apiClient.post('/funding/bank-links', {
      customer_id: customerId,
      plaid_public_token: plaidPublicToken,
    }),
}
