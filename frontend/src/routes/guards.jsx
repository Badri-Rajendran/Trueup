import { Navigate, useLocation } from 'react-router-dom'
import { useSession } from '../contexts/SessionContext.jsx'
import { useIdentityStatus } from '../features/onboarding/hooks/useIdentityStatus.js'
import { defaultRouteForPrincipal } from './defaultRoute.js'

/** Route guards live at the router level (structure.md §3), shared across every protected route. */
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
    return <Navigate to={defaultRouteForPrincipal(principal)} replace />
  }

  return children
}

/**
 * Gates customer routes (§2.3) on KYC + account approval (FR-3, ADR 21); staff pass through.
 * Fails closed: a load error is treated as not-yet-approved (regulatory gate, not a UX nicety).
 *
 * `useIdentityStatus` reads/writes the shared cache on `SessionContext` (structure.md §4), not
 * component-local state -- so this guard remounting as a customer bounces between `/onboarding`
 * and a protected route (`/onboarding` is a sibling route outside this wrapper, see App.jsx) does
 * NOT re-fetch `/identity/status` every time; only the first mount per session (cache still idle)
 * or a live `identity_status_changed` push does.
 */
export function RequireOnboarded({ children }) {
  const { status, principal } = useSession()
  const location = useLocation()
  const isCustomer = principal?.role === 'customer'
  const identity = useIdentityStatus(isCustomer ? principal.id : null)

  if (status === 'loading') {
    return null
  }

  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (!isCustomer) {
    return children
  }

  if (identity.status === 'idle' || identity.status === 'loading') {
    return null
  }

  const isApproved = identity.kycStatus === 'approved' && identity.accountApprovalStatus === 'approved'
  if (!isApproved) {
    return <Navigate to="/onboarding" replace />
  }

  return children
}
