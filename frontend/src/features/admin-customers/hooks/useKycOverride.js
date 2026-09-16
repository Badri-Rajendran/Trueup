import { useCallback, useState } from 'react'
import { adminCustomersApi } from '../api/adminCustomersApi.js'

export function useKycOverride() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const submit = useCallback(async (customerId, reason) => {
    setStatus('submitting')
    setError(null)
    try {
      const status = await adminCustomersApi.submitKycOverride(customerId, reason)
      setStatus('submitted')
      return status
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, submit }
}
