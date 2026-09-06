import { apiClient } from '../../../services/apiClient.js'

export const fundingApi = {
  deposit: (payload, idempotencyKey) => apiClient.post('/funding/deposits', payload, { idempotencyKey }),
  withdraw: (payload, idempotencyKey) => apiClient.post('/funding/withdrawals', payload, { idempotencyKey }),
  getCurrentBankLink: () => apiClient.get('/funding/bank-links/current'),
  // {withdrawable, investable} — never merge into one figure (design-system §8.2).
  getCashSummary: () => apiClient.get('/funding/cash-summary'),
}
