import { useCallback, useEffect, useMemo, useState } from 'react'
import { lotsApi } from '../api/lotsApi.js'
import { filterLotsByStatus, sortLots } from '../utils/lotSummary.js'

const IDLE = { status: 'idle', lots: [], error: null }
const DEFAULT_SORT = { column: 'symbol', direction: 'asc' }

/** Owns the fetch plus the client-side filter/sort UI state (no server-side params exist for
 * either — structure.md §5/§6) — `visibleLots` is the memoized, derived view; `lots` stays the raw
 * fetched list for page-level totals that must reflect the whole account regardless of the filter. */
export function useLots() {
  const [state, setState] = useState(IDLE)
  const [statusFilter, setStatusFilter] = useState('all')
  const [sort, setSort] = useState(DEFAULT_SORT)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const lots = await lotsApi.list()
      setState({ status: 'loaded', lots, error: null })
    } catch (error) {
      setState({ status: 'error', lots: [], error })
    }
  }, [])

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

  return { ...state, visibleLots, statusFilter, setStatusFilter, sort, toggleSort, refetch }
}
