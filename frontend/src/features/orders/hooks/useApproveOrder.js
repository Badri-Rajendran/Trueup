import { useCallback, useState } from 'react'
import { ordersApi } from '../api/ordersApi.js'

/**
 * `POST /orders/:id/approve` — an above-threshold order's broker submission is enqueued at
 * approval time, so a failure here must never optimistically flip the order to approved
 * (`structure.md` §6): the order stays `awaiting_approval` until this actually succeeds.
 */
export function useApproveOrder() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const approve = useCallback(async (orderId) => {
    setStatus('submitting')
    setError(null)
    try {
      const data = await ordersApi.approve(orderId)
      setStatus('submitted')
      return data
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, approve }
}
