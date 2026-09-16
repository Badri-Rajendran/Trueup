// Builds the `?cursor=&limit=` query string every paginated list endpoint accepts
// (backend/app/controllers/api/{orders,lots,funding,valuation,statements}.py). `after` is the
// opaque `next_cursor` a prior page returned; sent as the `cursor` param, the name the backend
// actually reads.
export function paginationQuery({ after, limit } = {}) {
  const params = new URLSearchParams()
  if (after) params.set('cursor', after)
  if (limit) params.set('limit', limit)
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}
