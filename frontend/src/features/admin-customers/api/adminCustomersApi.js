// Admin customer directory/detail/KYC-override routes (S8 §4 rows 1, 2, 5). Adviser/admin-only --
// see backend/app/controllers/admin/{customers,kyc_overrides}.py.
import { apiClient } from '../../../services/apiClient.js'

export const adminCustomersApi = {
  search: (query, { after, limit } = {}) => {
    const params = new URLSearchParams({ query })
    if (after) params.set('cursor', after)
    if (limit) params.set('limit', String(limit))
    return apiClient.get(`/admin/customers?${params.toString()}`)
  },
  getDetail: (customerId) => apiClient.get(`/admin/customers/${customerId}`),
  // Unconditionally reopens a locked-`rejected` KYC status to `pending` (S8 §4 row 5) -- there is
  // no approve/reject decision to send, only an audit `reason`.
  submitKycOverride: (customerId, reason) => apiClient.post(`/admin/kyc-overrides/${customerId}`, { reason }),
}
