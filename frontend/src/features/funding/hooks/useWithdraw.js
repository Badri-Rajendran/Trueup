import { useCallback, useState } from 'react'
import { useIdempotencyKey } from '../../../hooks/useIdempotencyKey.js'
import { fundingApi } from '../api/fundingApi.js'

export function useWithdraw(customerId) {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const { getKey, reset } = useIdempotencyKey()

  const withdraw = useCallback(
    async (amount) => {
      setStatus('submitting')
      setError(null)
      try {
        const data = await fundingApi.withdraw({ customer_id: customerId, amount }, getKey())
        setStatus('submitted')
        reset()
        return data
      } catch (err) {
        setError(err)
        setStatus('error')
        reset()
        throw err
      }
    },
    [customerId, getKey, reset],
  )

  return { status, error, withdraw }
}
