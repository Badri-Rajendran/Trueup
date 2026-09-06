// Shared infrastructure for every domain with no live backend yet (portfolio, lots, fees, chat,
// admin-customers, statement export — main's Phase 4 dispatch). A domain's `api/*.js` file uses
// this instead of `services/apiClient.js`, and instead of hand-rolling its own latency/state
// mechanism, so every mock behaves the same way and lives in one place to swap out later.

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

/**
 * A small in-memory store per domain namespace, seeded once via `seedFactory()` and then returned
 * by reference on every later call — mutating the returned object (an assignment, a resolved KYC
 * override, an attached payment method) persists for the rest of the browser session, the same
 * "real backend, no page reload" feel a live API would have, without inventing a fake endpoint.
 */
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
