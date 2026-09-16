import { useCallback, useEffect, useState } from 'react'
import { securitiesApi } from '../api/securitiesApi.js'

const IDLE = { status: 'idle', securities: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'

/**
 * The tradable/watchable security catalogue — `GET /api/v1/securities` (Task 2). Moved from
 * `features/portfolio/hooks/useSecurities.js`, which derived an orderable universe from
 * `/portfolios/models`' target weights only (no price, no full catalogue); this hook calls the
 * catalogue endpoint directly, so every security carries `last_close` for price display.
 */
export function useSecurities() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await securitiesApi.list()
      setState({ status: 'loaded', securities: data.securities, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', securities: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await securitiesApi.list({ after: state.nextCursor })
      setState((prev) => ({
        status: 'loaded',
        securities: [...prev.securities, ...data.securities],
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
