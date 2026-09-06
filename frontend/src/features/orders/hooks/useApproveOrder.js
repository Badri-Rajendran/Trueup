import { useCallback, useState } from 'react'
import { ordersApi } from '../api/ordersApi.js'

// structure.md §6: never optimistically flip to approved before the request succeeds.
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
