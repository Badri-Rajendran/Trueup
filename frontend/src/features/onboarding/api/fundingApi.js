import { apiClient } from '../../../services/apiClient.js'

// Bank-link exchange only (structure.md §3); deposits/withdrawals live in `funding`.
export const fundingApi = {
  createLinkToken: (customerId) => apiClient.post('/funding/link-token', { customer_id: customerId }),
  createBankLink: (customerId, plaidPublicToken) =>
    apiClient.post('/funding/bank-links', {
      customer_id: customerId,
      plaid_public_token: plaidPublicToken,
    }),
}
