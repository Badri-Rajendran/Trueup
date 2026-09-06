import { useCallback, useState } from 'react'
import { feesApi } from '../api/feesApi.js'

export function usePaymentMethod(customerId) {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const attach = useCallback(
    async (paymentMethodId) => {
      setStatus('submitting')
      setError(null)
      try {
        const data = await feesApi.attachPaymentMethod(customerId, paymentMethodId)
        setStatus('submitted')
        return data
      } catch (err) {
        setError(err)
        setStatus('error')
        throw err
      }
    },
    [customerId],
  )

  return { status, error, attach }
}
