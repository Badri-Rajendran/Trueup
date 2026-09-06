// S9 rebalancing / model portfolios — GET /portfolios/models, GET+POST /portfolios/assignment.
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
}
