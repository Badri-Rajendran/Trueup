import { apiClient } from '../../../services/apiClient.js'

// `balance`/`returns` aren't wired here yet — their only consumer, Dashboard, also needs
// `GET /portfolios/assignment` (S9/portfolio, a Phase 4 mock domain) for its holdings snapshot;
// added once Dashboard is assembled.
export const valuationApi = {
  getHistory: () => apiClient.get('/valuation/history'),
}
