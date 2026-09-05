import { Navigate, useLocation } from 'react-router-dom'
import { useSession } from '../contexts/SessionContext.jsx'
import { useIdentityStatus } from '../features/onboarding/hooks/useIdentityStatus.js'

/**
 * Route guards live at the router level (`structure.md` §3), not per-page, since the guard logic
 * is shared across every protected route.
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

/**
 * Gates the customer-app routes (§2.3) on both KYC and account approval being `approved` (FR-3,
 * ADR 21) — staff/adviser principals never onboard, so they pass straight through. Fails closed:
 * a load error is treated the same as "not yet approved" rather than granting access on an
 * inconclusive check, since this is a regulatory gate, not a UX nicety.
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
