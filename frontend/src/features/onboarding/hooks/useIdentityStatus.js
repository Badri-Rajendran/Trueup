import { useCallback, useEffect, useRef, useState } from 'react'
import { identityApi } from '../api/identityApi.js'

const IDLE = { status: 'idle', kycStatus: null, accountApprovalStatus: null, error: null }

// A still-pending refresh triggers a live outbound Stripe Identity poll (identity.py's
// get_identity_status), not a cheap read, and shares a single 30/min-per-IP bucket with
// RequireOnboarded's own background calls on every protected-route navigation -- a customer
// repeatedly clicking "Refresh status" could burn through that shared budget for the whole app.
const REFETCH_COOLDOWN_MS = 10_000

// GET /identity/status/<customer_id>; pass null for non-customer principals.
export function useIdentityStatus(customerId) {
  const [state, setState] = useState(IDLE)
  const [cooldownRemainingMs, setCooldownRemainingMs] = useState(0)
  const lastFetchedAtRef = useRef(0)

  const fetchNow = useCallback(async () => {
    if (!customerId) {
      setState(IDLE)
      return
    }
    lastFetchedAtRef.current = Date.now()
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await identityApi.getStatus(customerId)
      setState({
        status: 'loaded',
        kycStatus: data.kyc_status,
        accountApprovalStatus: data.account_approval_status,
        error: null,
      })
    } catch (error) {
      setState({ status: 'error', kycStatus: null, accountApprovalStatus: null, error })
    }
  }, [customerId])

  // The initial mount fetch below always bypasses this -- there is nothing to cool down from yet.
  // Every other caller (the "Refresh status" button, KycStep's onCompleted, ErrorState's onRetry)
  // goes through this throttled path, since a spammed retry deserves the same protection as a
  // spammed manual refresh.
  const refetch = useCallback(() => {
    if (Date.now() - lastFetchedAtRef.current < REFETCH_COOLDOWN_MS) {
      return
    }
    fetchNow()
  }, [fetchNow])

  useEffect(() => {
    fetchNow()
  }, [fetchNow])

  // Ticks the remaining cooldown down to 0 so the UI can show "Try again in Ns" and re-enable
  // itself without polling Date.now() from the caller.
  useEffect(() => {
    if (state.status !== 'loaded' && state.status !== 'error') return
    const update = () => {
      setCooldownRemainingMs(Math.max(0, REFETCH_COOLDOWN_MS - (Date.now() - lastFetchedAtRef.current)))
    }
    update()
    const interval = setInterval(update, 250)
    return () => clearInterval(interval)
  }, [state.status])

  return {
    ...state,
    refetch,
    canRefetch: cooldownRemainingMs === 0,
    cooldownRemainingSeconds: Math.ceil(cooldownRemainingMs / 1000),
  }
}
