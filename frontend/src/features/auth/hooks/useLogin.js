import { useCallback, useState } from 'react'
import { useSession } from '../../../contexts/SessionContext.jsx'
import { apiClient } from '../../../services/apiClient.js'
import { authApi } from '../api/authApi.js'

// Single status covers login + MFA:
// idle|submitting|mfa_enroll_required|enrolling|mfa_required|submitting_mfa|submitted|error|mfa_error.
export function useLogin() {
  const { setAuthenticated } = useSession()
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  // The provisioning secret + otpauth:// URI, held only for the enrollment screen.
  const [enrollment, setEnrollment] = useState(null)

  const login = useCallback(
    async ({ email, password, remember }) => {
      setStatus('submitting')
      setError(null)
      try {
        const response = await authApi.login({ email, password, remember })
        if (response.mfa_pending) {
          // Pending response's own csrf_token, not the session's final one.
          apiClient.setCsrfToken(response.csrf_token)
          // A staff account with no authenticator yet must enroll before a code exists to enter;
          // sending it straight to the code box is the dead end /mfa/verify rejects with 403.
          setStatus(response.mfa_enrolled ? 'mfa_required' : 'mfa_enroll_required')
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

  const enrollMfa = useCallback(async () => {
    setStatus('enrolling')
    setError(null)
    try {
      const response = await authApi.enrollMfa()
      setEnrollment({ secret: response.secret, provisioningUri: response.provisioning_uri })
      setStatus('mfa_required')
    } catch (err) {
      // 409 mfa_already_enrolled: the account gained a secret between login and here (a second
      // device, or a concurrent enrollment). Nothing is wrong — go to code entry.
      if (err?.code === 'mfa_already_enrolled') {
        setStatus('mfa_required')
        return
      }
      setError(err)
      setStatus('mfa_enroll_error')
      throw err
    }
  }, [])

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

  return { status, error, enrollment, login, enrollMfa, verifyMfa }
}
