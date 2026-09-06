import { apiClient } from '../../../services/apiClient.js'

export const adminBreaksApi = {
  listOpen: () => apiClient.get('/admin/breaks?status=open'),
  resolve: (breakId, resolutionNote) =>
    apiClient.post(`/admin/breaks/${breakId}/resolve`, { resolution_note: resolutionNote }),
}
