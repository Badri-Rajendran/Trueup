import { apiClient } from '../../../services/apiClient.js'

// `export` isn't wired here yet — no export-as-file endpoint exists (Phase 4 mock domain).
export const statementsApi = {
  list: () => apiClient.get('/statements'),
  get: (periodStart, publishWatermark) => {
    const query = publishWatermark ? `?publish_watermark=${encodeURIComponent(publishWatermark)}` : ''
    return apiClient.get(`/statements/${periodStart}${query}`)
  },
}
