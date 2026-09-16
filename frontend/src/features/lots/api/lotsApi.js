// S8 tax lots — GET /lots (backend/app/views/lots.py). Wire fields (Money/Units/Price strings,
// snake_case) pass straight through with zero camelCase mapping layer, matching feesApi.js's
// convention. No server-side sort/filter exists (client-side only, useLots.js) — pagination
// (`?cursor=&limit=`) is the only server-side list param, capped by its own 60/min rate limit.
import { apiClient } from '../../../services/apiClient.js'
import { paginationQuery } from '../../../utils/paginationQuery.js'

export const lotsApi = {
  list: (pagination) => apiClient.get(`/lots${paginationQuery(pagination)}`),
}
