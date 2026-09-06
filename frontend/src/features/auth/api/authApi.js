import { apiClient } from '../../../services/apiClient.js'

export const authApi = {
  register: (payload) => apiClient.post('/auth/register', payload),
  // Returns AuthResponse or MfaPendingResponse; callers branch on `mfa_pending`.
  login: (payload) => apiClient.post('/auth/login', payload),
  verifyMfa: (payload) => apiClient.post('/auth/mfa/verify', payload),
  logout: () => apiClient.post('/auth/logout'),
}
