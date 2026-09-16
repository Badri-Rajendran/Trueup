import { apiClient } from '../../../services/apiClient.js'
import { paginationQuery } from '../../../utils/paginationQuery.js'

export const ordersApi = {
  list: (pagination) => apiClient.get(`/orders${paginationQuery(pagination)}`),
  get: (orderId) => apiClient.get(`/orders/${orderId}`),
  create: (payload, idempotencyKey) => apiClient.post('/orders', payload, { idempotencyKey }),
  // No request body needed.
  approve: (orderId) => apiClient.post(`/orders/${orderId}/approve`),
}
