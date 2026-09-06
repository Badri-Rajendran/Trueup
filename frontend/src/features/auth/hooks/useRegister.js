import { useCallback, useState } from 'react'
import { authApi } from '../api/authApi.js'

export function useRegister() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const register = useCallback(async ({ email, password }) => {
    setStatus('submitting')
    setError(null)
    try {
      const response = await authApi.register({ email, password })
      setStatus('submitted')
      return response
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, register }
}
