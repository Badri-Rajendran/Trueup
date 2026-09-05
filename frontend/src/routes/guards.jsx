import { Navigate, useLocation } from 'react-router-dom'
import { useSession } from '../contexts/SessionContext.jsx'

/**
 * Route guards live at the router level (`structure.md` §3), not per-page, since the guard logic
 * is shared across every protected route.
 *
 * `RequireOnboarded` (KYC/account-approval gating for `/onboarding` → customer-app routes) is not
 * implemented yet — `SessionContext` only carries `{id, email, role}` from `GET /auth/session`
 * today; the onboarding feature's own `GET /identity/status` hook (Phase 1) is what that guard
 * needs to read from, so it lands alongside that hook rather than as a stub with no real check.
 */
export function RequireAuth({ children }) {
  const { status } = useSession()
  const location = useLocation()

  if (status === 'loading') {
    return null
  }

  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children
}

export function RequireRole({ roles, children }) {
  const { status, principal } = useSession()
  const location = useLocation()

  if (status === 'loading') {
    return null
  }

  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (!roles.includes(principal.role)) {
    return <Navigate to="/dashboard" replace />
  }

  return children
}
