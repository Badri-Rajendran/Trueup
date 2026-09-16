import { apiClient } from '../../../services/apiClient.js'
import { paginationQuery } from '../../../utils/paginationQuery.js'

export const fundingApi = {
  deposit: (payload, idempotencyKey) => apiClient.post('/funding/deposits', payload, { idempotencyKey }),
  withdraw: (payload, idempotencyKey) => apiClient.post('/funding/withdrawals', payload, { idempotencyKey }),
  getCurrentBankLink: () => apiClient.get('/funding/bank-links/current'),
  // design-system.md §8.2
  getCashSummary: () => apiClient.get('/funding/cash-summary'),
  getFundingHistory: (pagination) => apiClient.get(`/funding/history${paginationQuery(pagination)}`),
}
