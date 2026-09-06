import { useCallback, useRef } from 'react'

/** Generates and holds a client idempotency key until `reset()`; retried submits reuse it. */
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

  /** Resets only on a final, non-retryable outcome; a status===0 network failure keeps the key. */
  const resetIfFinal = useCallback((error) => {
    if (!error || error.status !== 0) {
      keyRef.current = null
    }
  }, [])

  return { getKey, reset, resetIfFinal }
}
