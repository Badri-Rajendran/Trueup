import { apiClient } from '../../../services/apiClient.js'

export const identityApi = {
  startKycSession: (customerId) => apiClient.post('/identity/kyc-sessions', { customer_id: customerId }),
  getStatus: (customerId) => apiClient.get(`/identity/status/${customerId}`),
  // Stripe publishable key; not customer-scoped.
  getConfig: () => apiClient.get('/identity/config'),
}
