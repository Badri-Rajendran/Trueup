import { useCallback, useState } from 'react'
import { adminCustomersApi } from '../api/adminCustomersApi.js'

export function useKycOverride() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const submit = useCallback(async (customerId, decision) => {
    setStatus('submitting')
    setError(null)
    try {
      const customer = await adminCustomersApi.submitKycOverride(customerId, decision)
      setStatus('submitted')
      return customer
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, submit }
}
