// S9 rebalancing / model portfolios
import { apiClient } from '../../../services/apiClient.js'

export const portfoliosApi = {
  getModels: async () => {
    const data = await apiClient.get('/portfolios/models')
    return data.models
  },
  getAssignment: async () => {
    const data = await apiClient.get('/portfolios/assignment')
    return data.assignment
  },
  assign: async (customerId, modelPortfolioId) => {
    const data = await apiClient.post('/portfolios/assignment', {
      customer_id: customerId,
      model_portfolio_id: modelPortfolioId,
    })
    return data
  },
  getHoldings: () => apiClient.get('/portfolios/holdings'),
  // `range` is the backend's own literal enum (1m|3m|6m|1y|all) — `app/controllers/api/portfolios.py`'s `_PerformanceQuery`.
  getPerformance: (range) => apiClient.get(`/portfolios/performance?range=${range}`),
}
