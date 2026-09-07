import { apiClient } from '../../../services/apiClient.js'

// `export` isn't wired here yet -- the real backend route (GET /statements/<period>/export)
// exists and is tested (backend/app/controllers/api/statements.py), the frontend just hasn't
// been pointed at it. See docs/superpowers/specs/2026-09-05-frontend-completion-design.md.
export const statementsApi = {
  list: () => apiClient.get('/statements'),
  get: (periodStart, publishWatermark) => {
    const query = publishWatermark ? `?publish_watermark=${encodeURIComponent(publishWatermark)}` : ''
    return apiClient.get(`/statements/${periodStart}${query}`)
  },
}
