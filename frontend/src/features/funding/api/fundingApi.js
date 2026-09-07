import { apiClient } from '../../../services/apiClient.js'

export const fundingApi = {
  deposit: (payload, idempotencyKey) => apiClient.post('/funding/deposits', payload, { idempotencyKey }),
  withdraw: (payload, idempotencyKey) => apiClient.post('/funding/withdrawals', payload, { idempotencyKey }),
  getCurrentBankLink: () => apiClient.get('/funding/bank-links/current'),
  // design-system.md §8.2
  getCashSummary: () => apiClient.get('/funding/cash-summary'),
  getFundingHistory: () => apiClient.get('/funding/history'),
}
