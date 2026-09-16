import { apiClient } from '../../../services/apiClient.js'
import { paginationQuery } from '../../../utils/paginationQuery.js'

export const valuationApi = {
  getBalance: () => apiClient.get('/valuation/balance'),
  getReturns: (periodStart, periodEnd) =>
    apiClient.get(`/valuation/returns?period_start=${periodStart}&period_end=${periodEnd}`),
  getHistory: (pagination) => apiClient.get(`/valuation/history${paginationQuery(pagination)}`),
}
