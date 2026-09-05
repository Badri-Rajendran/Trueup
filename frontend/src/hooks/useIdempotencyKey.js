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

  return { getKey, reset }
}
