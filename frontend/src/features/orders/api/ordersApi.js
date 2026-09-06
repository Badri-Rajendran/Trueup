import { apiClient } from '../../../services/apiClient.js'

// `create` (POST /orders) isn't wired here yet — placing an order needs a security picker with no
// real backend yet (S9/portfolio, a Phase 4 mock domain); added once OrderForm lands.
export const ordersApi = {
  list: () => apiClient.get('/orders'),
  get: (orderId) => apiClient.get(`/orders/${orderId}`),
  // No request body — the backend resolves everything it needs from the order itself.
  approve: (orderId) => apiClient.post(`/orders/${orderId}/approve`),
}
