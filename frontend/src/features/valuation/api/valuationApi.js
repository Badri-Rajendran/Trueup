import { apiClient } from '../../../services/apiClient.js'

export const valuationApi = {
  getBalance: () => apiClient.get('/valuation/balance'),
  getReturns: (periodStart, periodEnd) =>
    apiClient.get(`/valuation/returns?period_start=${periodStart}&period_end=${periodEnd}`),
}
