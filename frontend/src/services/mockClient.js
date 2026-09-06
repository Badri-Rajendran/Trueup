// Shared mock infra (latency + in-memory store) for domains with no backend route yet (S8 lots, admin-customers).

const DEFAULT_LATENCY_MS = 300

function delay(ms = DEFAULT_LATENCY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Simulates a network round-trip: resolves with `value`, or rejects with `error` if given. */
async function request(value, { latency = DEFAULT_LATENCY_MS, error } = {}) {
  await delay(latency)
  if (error) {
    throw error
  }
  return value
}

const stores = new Map()

/** In-memory store per namespace, seeded once via `seedFactory()`; mutations persist for the session. */
function getStore(namespace, seedFactory) {
  if (!stores.has(namespace)) {
    stores.set(namespace, seedFactory())
  }
  return stores.get(namespace)
}

/** A stable id for mock data, deterministic per (namespace, key) so references stay stable across calls. */
function mockId(namespace, key) {
  return `mock-${namespace}-${key}`
}

export const mockClient = { request, delay, getStore, mockId }
