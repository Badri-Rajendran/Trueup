import { useCallback, useState } from 'react'
import { useIdempotencyKey } from '../../../hooks/useIdempotencyKey.js'
import { ordersApi } from '../api/ordersApi.js'

export function usePlaceOrder() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const { getKey, reset } = useIdempotencyKey()

  const placeOrder = useCallback(
    async ({ securityId, side, quantity, referencePrice }) => {
      setStatus('submitting')
      setError(null)
      try {
        const data = await ordersApi.create(
          { security_id: securityId, side, quantity, reference_price: referencePrice },
          getKey(),
        )
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
    [getKey, reset],
  )

  return { status, error, placeOrder }
}
