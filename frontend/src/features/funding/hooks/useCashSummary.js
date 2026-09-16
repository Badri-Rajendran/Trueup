import { useCallback, useEffect, useState } from 'react'
import { useLiveRefetch } from '../../../hooks/useLiveRefetch.js'
import { fundingApi } from '../api/fundingApi.js'

const IDLE = { status: 'idle', cashSummary: null, error: null, isRefreshing: false }

/**
 * `GET /funding/cash-summary` — the one place this fetch lives now. Originally split out of
 * `useFunding.js` for the Dashboard's own read-only use (task-8-brief.md); Task 10 finished the
 * split by moving `useFunding.js`'s post-submit `refresh()` cycle here too and deleting it, so the
 * Money page's deposit/withdraw forms and the Dashboard share one cash-summary fetch instead of
 * running a second, identical one.
 *
 * `refetch()` is the initial/retry path (`status` flips to `'loading'`, callers render their
 * skeleton again). `refresh()` is the post-submit path (a successful deposit/withdrawal) — it
 * re-fetches while keeping `status: 'loaded'` and flipping `isRefreshing` instead, so a successful
 * submit updates the balance in place rather than blanking the page back to skeletons.
 */
export function useCashSummary() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const cashSummary = await fundingApi.getCashSummary()
      setState({ status: 'loaded', cashSummary, error: null, isRefreshing: false })
    } catch (error) {
      setState({ status: 'error', cashSummary: null, error, isRefreshing: false })
    }
  }, [])

  const refresh = useCallback(async () => {
    setState((prev) => ({ ...prev, isRefreshing: true }))
    try {
      const cashSummary = await fundingApi.getCashSummary()
      setState((prev) => ({ ...prev, status: 'loaded', cashSummary, error: null, isRefreshing: false }))
    } catch {
      // The deposit/withdrawal itself already succeeded — only the re-fetch failed. Keep the
      // last-known-good balance on screen rather than blanking it over a transient error; the
      // next refetch()/refresh() will catch up.
      setState((prev) => ({ ...prev, isRefreshing: false }))
    }
  }, [])

  useLiveRefetch(['order_updated'], refetch)

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch, refresh }
}
