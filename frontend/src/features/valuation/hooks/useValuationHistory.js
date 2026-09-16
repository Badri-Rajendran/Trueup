import { useCallback, useEffect, useState } from 'react'
import { valuationApi } from '../api/valuationApi.js'

const IDLE = { status: 'idle', entries: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'

/** `GET /valuation/history` (S4 §7/§9) — always the live/current variant (ADR 6); S6's
 * as-published statement history is `useStatements.js`'s own hook, never this one. */
export function useValuationHistory() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await valuationApi.getHistory()
      setState({ status: 'loaded', entries: data.entries, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', entries: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await valuationApi.getHistory({ after: state.nextCursor })
      setState((prev) => ({
        status: 'loaded',
        entries: [...prev.entries, ...data.entries],
        nextCursor: data.next_cursor,
        error: null,
      }))
    } catch (error) {
      setState((prev) => ({ ...prev, status: 'error', error }))
    }
  }, [state.nextCursor, state.status])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch, loadMore }
}
