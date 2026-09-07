import { useCallback, useEffect, useState } from 'react'
import { fundingApi } from '../api/fundingApi.js'

const IDLE = { status: 'idle', cashSummary: null, entries: [], error: null, isRefreshing: false }

/**
 * Owns the Funding screen's two core fetches (`GET /cash-summary`, `GET /history`) as one
 * container — the double-fetch bug this replaces came from `CashSummary` running its own second
 * `/cash-summary` call on top of this same data (removed; `CashSummary` is now presentational).
 *
 * `refetch()` is the initial/retry path (`status` flips to `'loading'`, page renders its skeleton
 * again). `refresh()` is the post-submit path (a successful deposit/withdrawal) — it re-fetches
 * both endpoints while keeping `status: 'loaded'` and flipping `isRefreshing` instead, so a
 * successful submit updates the balance/history in place rather than blanking the page back to
 * skeletons.
 */
export function useFunding() {
  const [state, setState] = useState(IDLE)

  const load = useCallback(async () => {
    const [cashSummary, history] = await Promise.all([fundingApi.getCashSummary(), fundingApi.getFundingHistory()])
    return { cashSummary, entries: history.entries }
  }, [])

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const { cashSummary, entries } = await load()
      setState({ status: 'loaded', cashSummary, entries, error: null, isRefreshing: false })
    } catch (error) {
      setState({ status: 'error', cashSummary: null, entries: [], error, isRefreshing: false })
    }
  }, [load])

  const refresh = useCallback(async () => {
    setState((prev) => ({ ...prev, isRefreshing: true }))
    try {
      const { cashSummary, entries } = await load()
      setState((prev) => ({ ...prev, status: 'loaded', cashSummary, entries, error: null, isRefreshing: false }))
    } catch {
      // The deposit/withdrawal itself already succeeded — only the re-fetch failed. Keep the
      // last-known-good balance/history on screen rather than blanking it over a transient error;
      // the next refetch()/refresh() will catch up.
      setState((prev) => ({ ...prev, isRefreshing: false }))
    }
  }, [load])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch, refresh }
}
