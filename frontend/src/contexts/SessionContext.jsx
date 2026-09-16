import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { apiClient } from '../services/apiClient'

const SessionContext = createContext(undefined)

/**
 * `identityStatus`'s idle sentinel (structure.md §4: "Route guards read this rather than each
 * page re-fetching /identity/status"). Exported so `useIdentityStatus` -- the only writer, via
 * `setIdentityStatus` below -- can compare against the exact same shape without duplicating it.
 */
export const IDENTITY_STATUS_IDLE = { status: 'idle', kycStatus: null, accountApprovalStatus: null, error: null }

function principalFromAuthResponse(authResponse) {
  return { id: authResponse.id, email: authResponse.email, role: authResponse.role }
}

/**
 * Current identity, restored once on mount via `GET /auth/session` (the only way a reloaded page
 * can re-derive who is logged in and obtain a fresh CSRF token — both are only ever handed back in
 * a login/mfa-verify/session response body, never re-derivable client-side).
 */
export function SessionProvider({ children }) {
  const [status, setStatus] = useState('loading')
  const [principal, setPrincipal] = useState(null)
  const [identityStatus, setIdentityStatus] = useState(IDENTITY_STATUS_IDLE)

  const refresh = useCallback(async () => {
    setStatus('loading')
    try {
      const data = await apiClient.get('/auth/session')
      apiClient.setCsrfToken(data.csrf_token)
      setPrincipal(principalFromAuthResponse(data))
      setStatus('authenticated')
    } catch {
      apiClient.clearCsrfToken()
      setPrincipal(null)
      setStatus('anonymous')
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    try {
      await apiClient.post('/auth/logout')
    } finally {
      apiClient.clearCsrfToken()
      setPrincipal(null)
      setStatus('anonymous')
      // A stale approved/rejected verdict must never leak into the next session signed in on this
      // tab (e.g. a shared device) -- the next customer's `useIdentityStatus` mount starts idle
      // and fetches fresh, same as a first-ever login.
      setIdentityStatus(IDENTITY_STATUS_IDLE)
    }
  }, [])

  /** Called by login/mfa-verify flows with their response body, to avoid a redundant re-fetch of /auth/session. */
  const setAuthenticated = useCallback((authResponse) => {
    apiClient.setCsrfToken(authResponse.csrf_token)
    setPrincipal(principalFromAuthResponse(authResponse))
    setStatus('authenticated')
  }, [])

  return (
    <SessionContext.Provider
      value={{ status, principal, refresh, logout, setAuthenticated, identityStatus, setIdentityStatus }}
    >
      {children}
    </SessionContext.Provider>
  )
}

export function useSession() {
  const context = useContext(SessionContext)
  if (context === undefined) {
    throw new Error('useSession must be used within a SessionProvider')
  }
  return context
}
