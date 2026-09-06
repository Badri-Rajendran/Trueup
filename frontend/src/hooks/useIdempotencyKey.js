import { useCallback, useRef } from 'react'

/**
 * Generates a client-side idempotency key for a write, and keeps returning the same key across
 * re-renders until `reset()` is called — a retried submit (flaky connection) reuses the key so the
 * backend returns the original result instead of duplicating it. Callers reset once the write
 * settles (success or a final, non-retryable failure) so the *next* submit gets a fresh key.
 */
export function useIdempotencyKey() {
  const keyRef = useRef(null)

  const getKey = useCallback(() => {
    if (!keyRef.current) {
      keyRef.current = crypto.randomUUID()
    }
    return keyRef.current
  }, [])

  const reset = useCallback(() => {
    keyRef.current = null
  }, [])

  /**
   * Resets only for a final, non-retryable outcome — a network failure (`ApiError.status === 0`,
   * `apiClient.js`'s own signal for "the request itself never reached the server") keeps the same
   * key so a retried submit replays the original attempt instead of minting a new one.
   */
  const resetIfFinal = useCallback((error) => {
    if (!error || error.status !== 0) {
      keyRef.current = null
    }
  }, [])

  return { getKey, reset, resetIfFinal }
}
