import { useCallback, useState } from 'react'
import { useSession } from '../../../contexts/SessionContext.jsx'
import { apiClient } from '../../../services/apiClient.js'
import { authApi } from '../api/authApi.js'

/**
 * One merged `status` covers the whole login flow, including the staff/adviser MFA step, so no
 * combination of booleans can describe an impossible state (`frontend/CLAUDE.md`'s explicit rule):
 * 'idle' | 'submitting' | 'mfa_required' | 'submitting_mfa' | 'submitted' | 'error' | 'mfa_error'.
 * The two error states are distinct so a failed MFA code keeps the code step open with its own
 * error, rather than bouncing back to a generic "error" that could be misread as the credentials
 * step failing.
 */
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
          // The pending response's own csrf_token protects the /mfa/verify call that follows —
          // it is not the session's final token (that arrives once MFA completes).
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
