// S8 tax lots — GET /lots (backend/app/views/lots.py). Wire fields (Money/Units/Price strings,
// snake_case) pass straight through with zero camelCase mapping layer, matching feesApi.js's
// convention. No server-side sort/filter/pagination params exist — the endpoint returns every lot
// for the customer in one response (acquired_at ASC, id ASC), capped by its own 60/min rate limit.
import { apiClient } from '../../../services/apiClient.js'

export const lotsApi = {
  list: async () => {
    const data = await apiClient.get('/lots')
    return data.lots
  },
}
