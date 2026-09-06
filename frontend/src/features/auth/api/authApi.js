import { apiClient } from '../../../services/apiClient.js'

export const authApi = {
  register: (payload) => apiClient.post('/auth/register', payload),
  // Returns either a fully-authenticated AuthResponse, or a MfaPendingResponse
  // ({ mfa_pending: true, csrf_token }) for a staff/adviser account — both shapes carry
  // `mfa_pending`, so callers branch on that field alone.
  login: (payload) => apiClient.post('/auth/login', payload),
  verifyMfa: (payload) => apiClient.post('/auth/mfa/verify', payload),
  logout: () => apiClient.post('/auth/logout'),
}
