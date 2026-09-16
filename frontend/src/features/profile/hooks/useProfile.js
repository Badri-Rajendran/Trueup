import { useCallback, useEffect, useState } from 'react'
import { profileApi } from '../api/profileApi.js'

const IDLE = { status: 'idle', profile: null, error: null }

/**
 * `GET /profile`. No push event names a profile change (ADR 27 doesn't define one -- a customer
 * editing their own display name/phone/address has no reason to notify any other session), so
 * unlike the identity/order/cash hooks this has no `useLiveRefetch` subscription.
 */
export function useProfile() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const profile = await profileApi.get()
      setState({ status: 'loaded', profile, error: null })
    } catch (error) {
      setState({ status: 'error', profile: null, error })
    }
  }, [])

  // `PATCH /profile`'s own response is the fresh, authoritative profile -- applying it directly
  // here after a successful `ProfileForm` save updates the cache in place, the same way
  // `useCashSummary.refresh()` avoids a redundant round-trip after a deposit/withdrawal.
  const applyUpdate = useCallback((profile) => {
    setState({ status: 'loaded', profile, error: null })
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch, applyUpdate }
}
