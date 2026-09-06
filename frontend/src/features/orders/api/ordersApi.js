import { apiClient } from '../../../services/apiClient.js'

export const ordersApi = {
  list: () => apiClient.get('/orders'),
  get: (orderId) => apiClient.get(`/orders/${orderId}`),
  create: (payload, idempotencyKey) => apiClient.post('/orders', payload, { idempotencyKey }),
  // No request body needed.
  approve: (orderId) => apiClient.post(`/orders/${orderId}/approve`),
}
