import { useCallback, useEffect, useMemo, useState } from 'react'
import { lotsApi } from '../api/lotsApi.js'
import { filterLotsByStatus, sortLots } from '../utils/lotSummary.js'

const IDLE = { status: 'idle', lots: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'
const DEFAULT_SORT = { column: 'symbol', direction: 'asc' }

/** Owns the fetch plus the client-side filter/sort UI state (no server-side sort/filter params
 * exist — structure.md §5/§6, pagination is the only server-side list param) — `visibleLots` is
 * the memoized, derived view; `lots` stays the raw fetched (and accumulated, across `loadMore`)
 * list for page-level totals that must reflect the whole account regardless of the filter. */
export function useLots() {
  const [state, setState] = useState(IDLE)
  const [statusFilter, setStatusFilter] = useState('all')
  const [sort, setSort] = useState(DEFAULT_SORT)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await lotsApi.list()
      setState({ status: 'loaded', lots: data.lots, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', lots: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await lotsApi.list({ after: state.nextCursor })
      setState((prev) => ({
        status: 'loaded',
        lots: [...prev.lots, ...data.lots],
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

  const toggleSort = useCallback((column) => {
    setSort((prev) => {
      if (prev.column !== column) return { column, direction: 'asc' }
      return { column, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
    })
  }, [])

  const visibleLots = useMemo(
    () => sortLots(filterLotsByStatus(state.lots, statusFilter), sort),
    [state.lots, statusFilter, sort],
  )

  return { ...state, visibleLots, statusFilter, setStatusFilter, sort, toggleSort, refetch, loadMore }
}
