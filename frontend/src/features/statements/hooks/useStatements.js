import { useCallback, useEffect, useMemo, useState } from 'react'
import { statementsApi } from '../api/statementsApi.js'
import { groupStatementsByPeriod } from '../groupStatementsByPeriod.js'

const IDLE = { status: 'idle', statements: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'

/** `periods` is derived from the raw, accumulated `statements` list on every render (grouping is
 * cheap and must re-run over the whole list — not just the newest page — since `loadMore` can
 * append another version of a period already on an earlier page). */
export function useStatements() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await statementsApi.list()
      setState({ status: 'loaded', statements: data.statements, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', statements: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await statementsApi.list({ after: state.nextCursor })
      setState((prev) => ({
        status: 'loaded',
        statements: [...prev.statements, ...data.statements],
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

  const periods = useMemo(() => groupStatementsByPeriod(state.statements), [state.statements])

  return { ...state, periods, refetch, loadMore }
}
