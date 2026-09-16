import { useCallback, useEffect, useState } from 'react'
import { fundingApi } from '../api/fundingApi.js'

const IDLE = { status: 'idle', entries: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'

/** `GET /funding/history` (S2 §6) — split out of what was `useFunding.js`; that hook is gone now
 * (Task 10 finished the split), its cash-summary half folded into `useCashSummary.js` instead. */
export function useFundingHistory() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await fundingApi.getFundingHistory()
      setState({ status: 'loaded', entries: data.entries, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', entries: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await fundingApi.getFundingHistory({ after: state.nextCursor })
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
