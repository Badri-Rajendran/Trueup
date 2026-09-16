import { useCallback, useEffect, useRef, useState } from 'react'
import { IDENTITY_STATUS_IDLE, useSession } from '../../../contexts/SessionContext.jsx'
import { useLiveRefetch } from '../../../hooks/useLiveRefetch.js'
import { identityApi } from '../api/identityApi.js'

// A still-pending refresh triggers a live outbound Stripe Identity poll (identity.py's
// get_identity_status), not a cheap read, and shares a single 30/min-per-IP bucket across every
// customer session -- the manual "Refresh status" button is throttled client-side so repeatedly
// clicking it can't burn through that budget.
const REFETCH_COOLDOWN_MS = 10_000

/**
 * `GET /identity/status/<customer_id>`, backed by the shared cache on `SessionContext`
 * (structure.md §4) instead of component-local state. Every consumer -- `RequireOnboarded`,
 * `OnboardingPage`, `AccountPage` -- reads and writes the *same* cache, so the status is fetched
 * once per session (whichever consumer mounts first while it's still `'idle'`) rather than once
 * per mount. A remount (e.g. `RequireOnboarded` unmounting/remounting as a customer bounces
 * between `/onboarding` and a protected route) finds the cache already `'loaded'` and skips the
 * network call entirely -- this is the fix for the previous per-navigation refetch. The cache is
 * refreshed only by an explicit `refetch()` call or by one of the two live pushes below; a plain
 * re-render never re-fetches.
 */
export function useIdentityStatus(customerId) {
  const { identityStatus, setIdentityStatus } = useSession()
  const [cooldownRemainingMs, setCooldownRemainingMs] = useState(0)
  const lastFetchedAtRef = useRef(0)

  const fetchNow = useCallback(async () => {
    if (!customerId) {
      setIdentityStatus(IDENTITY_STATUS_IDLE)
      return
    }
    lastFetchedAtRef.current = Date.now()
    setIdentityStatus((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await identityApi.getStatus(customerId)
      setIdentityStatus({
        status: 'loaded',
        kycStatus: data.kyc_status,
        accountApprovalStatus: data.account_approval_status,
        error: null,
      })
    } catch (error) {
      setIdentityStatus({ status: 'error', kycStatus: null, accountApprovalStatus: null, error })
    }
  }, [customerId, setIdentityStatus])

  // The manual path (the "Refresh status" button, KycStep's onCompleted, ErrorState's onRetry) --
  // cooldown-guarded, since a spammed click deserves the same protection the old per-navigation
  // refetch needed.
  const refetch = useCallback(() => {
    if (Date.now() - lastFetchedAtRef.current < REFETCH_COOLDOWN_MS) {
      return
    }
    fetchNow()
  }, [fetchNow])

  // The server-pushed verdict change (ADR 20) always wins over the cooldown: it only fires when a
  // status genuinely changed, not on every navigation, so throttling it could leave a customer
  // looking at a stale verdict until their next manual refresh or full page reload. The two gates
  // publish independently (`EventPublisher.identity_status_changed`'s own docstring: "never merged
  // into one event"), as `kyc_status_changed`/`account_approval_status_changed` -- there is no
  // single `identity_status_changed` event_type on the wire.
  useLiveRefetch(['kyc_status_changed', 'account_approval_status_changed'], fetchNow)

  // Populate-once: fetch only while the shared cache is still idle. Re-runs whenever `status`
  // changes (fetchNow's own transitions included), but the condition is false by the time that
  // happens, so this never loops -- it just means a fresh customerId (e.g. anonymous -> customer)
  // gets exactly one fetch, and every later remount sharing the same cache is a no-op.
  useEffect(() => {
    if (!customerId) {
      if (identityStatus.status !== 'idle') {
        setIdentityStatus(IDENTITY_STATUS_IDLE)
      }
      return
    }
    if (identityStatus.status === 'idle') {
      fetchNow()
    }
  }, [customerId, identityStatus.status, fetchNow, setIdentityStatus])

  // Ticks the remaining cooldown down to 0 so the UI can show "Try again in Ns" and re-enable
  // itself without polling Date.now() from the caller.
  useEffect(() => {
    if (identityStatus.status !== 'loaded' && identityStatus.status !== 'error') return
    const update = () => {
      setCooldownRemainingMs(Math.max(0, REFETCH_COOLDOWN_MS - (Date.now() - lastFetchedAtRef.current)))
    }
    update()
    const interval = setInterval(update, 250)
    return () => clearInterval(interval)
  }, [identityStatus.status])

  return {
    ...identityStatus,
    refetch,
    canRefetch: cooldownRemainingMs === 0,
    cooldownRemainingSeconds: Math.ceil(cooldownRemainingMs / 1000),
  }
}
