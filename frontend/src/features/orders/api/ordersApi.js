import { apiClient } from '../../../services/apiClient.js'

export const ordersApi = {
  list: () => apiClient.get('/orders'),
  get: (orderId) => apiClient.get(`/orders/${orderId}`),
  create: (payload, idempotencyKey) => apiClient.post('/orders', payload, { idempotencyKey }),
  // No request body — the backend resolves everything it needs from the order itself.
  approve: (orderId) => apiClient.post(`/orders/${orderId}/approve`),
}
