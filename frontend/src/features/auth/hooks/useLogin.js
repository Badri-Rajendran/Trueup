import { useCallback, useState } from 'react'
import { useSession } from '../../../contexts/SessionContext.jsx'
import { apiClient } from '../../../services/apiClient.js'
import { authApi } from '../api/authApi.js'

// Single status covers login + MFA: idle|submitting|mfa_required|submitting_mfa|submitted|error|mfa_error.
export function useLogin() {
  const { setAuthenticated } = useSession()
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const login = useCallback(
    async ({ email, password, remember }) => {
      setStatus('submitting')
      setError(null)
      try {
        const response = await authApi.login({ email, password, remember })
        if (response.mfa_pending) {
          // Pending response's own csrf_token, not the session's final one.
          apiClient.setCsrfToken(response.csrf_token)
          setStatus('mfa_required')
          return { mfaRequired: true }
        }
        setAuthenticated(response)
        setStatus('submitted')
        return { mfaRequired: false }
      } catch (err) {
        setError(err)
        setStatus('error')
        throw err
      }
    },
    [setAuthenticated],
  )

  const verifyMfa = useCallback(
    async (code) => {
      setStatus('submitting_mfa')
      setError(null)
      try {
        const response = await authApi.verifyMfa({ code })
        setAuthenticated(response)
        setStatus('submitted')
      } catch (err) {
        setError(err)
        setStatus('mfa_error')
        throw err
      }
    },
    [setAuthenticated],
  )

  return { status, error, login, verifyMfa }
}
