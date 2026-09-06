// Fetch wrapper for the Trueup API. Same-origin `/api/v1` only — no CORS, SameSite=Strict cookie.
const API_BASE = '/api/v1'

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

let csrfToken = null

/** Set after a login/mfa-verify/session-restore response — the only places the server issues one. */
function setCsrfToken(token) {
  csrfToken = token
}

function getCsrfToken() {
  return csrfToken
}

function clearCsrfToken() {
  csrfToken = null
}

/** Typed error normalized from the API's RFC 9457 problem-details body: {type, title, status, code, correlation_id}. */
class ApiError extends Error {
  constructor({ status, code, title, type, correlationId }) {
    super(title || `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.type = type
    this.correlationId = correlationId
  }
}

async function parseBody(response) {
  // Success bodies are application/json; error bodies are application/problem+json (RFC 9457).
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('json')) return null
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function request(path, { method = 'GET', body, headers, idempotencyKey, signal } = {}) {
  const finalHeaders = { Accept: 'application/json', ...headers }
  let finalBody

  if (body !== undefined) {
    finalHeaders['Content-Type'] = 'application/json'
    finalBody = JSON.stringify(body)
  }

  if (MUTATING_METHODS.has(method) && csrfToken) {
    finalHeaders['X-CSRFToken'] = csrfToken
  }

  if (idempotencyKey) {
    finalHeaders['Idempotency-Key'] = idempotencyKey
  }

  const fetchOptions = { method, credentials: 'include', headers: finalHeaders, signal }
  if (finalBody !== undefined) {
    fetchOptions.body = finalBody
  }

  let response
  try {
    response = await fetch(`${API_BASE}${path}`, fetchOptions)
  } catch {
    throw new ApiError({ status: 0, code: 'network_error', title: 'Network request failed' })
  }

  const data = await parseBody(response)

  if (!response.ok) {
    throw new ApiError({
      status: response.status,
      code: data?.code,
      title: data?.title,
      type: data?.type,
      correlationId: data?.correlation_id,
    })
  }

  return data
}

export const apiClient = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
  put: (path, body, options) => request(path, { ...options, method: 'PUT', body }),
  patch: (path, body, options) => request(path, { ...options, method: 'PATCH', body }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
  setCsrfToken,
  getCsrfToken,
  clearCsrfToken,
}

export { ApiError }
