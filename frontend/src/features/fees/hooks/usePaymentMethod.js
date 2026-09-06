import { useCallback, useState } from 'react'
import { feesApi } from '../api/feesApi.js'

export function usePaymentMethod() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const attach = useCallback(async (paymentMethod) => {
    setStatus('submitting')
    setError(null)
    try {
      const data = await feesApi.attachPaymentMethod(paymentMethod)
      setStatus('submitted')
      return data
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, attach }
}
