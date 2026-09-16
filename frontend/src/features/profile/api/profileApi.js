import { apiClient } from '../../../services/apiClient.js'

// ADR 27: self-scoped, no customer_id param on either route -- the session decides whose profile
// this is, server-side.
export const profileApi = {
  get: () => apiClient.get('/profile'),
  update: (fields) => apiClient.patch('/profile', fields),
}
