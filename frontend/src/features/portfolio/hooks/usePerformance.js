import { useCallback, useEffect, useState } from 'react'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = {
  status: 'idle',
  range: null,
  periodStart: null,
  periodEnd: null,
  cumulativeTwr: null,
  isProvisional: false,
  points: [],
  error: null,
}

/**
 * `GET /portfolios/performance?range=` (ADR 26, live series) — `range` is one of the backend's own
 * literal enum values (`1m|3m|6m|1y|all`, `app/controllers/api/portfolios.py`'s `_PerformanceQuery`).
 * Refetches whenever `range` changes; the prior range's points stay in state through the `loading`
 * transition (a spread of `prev`) so `ValuationChart` doesn't flash to empty on every range click —
 * it only replaces on the next success or error.
 */
export function usePerformance(range) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await portfoliosApi.getPerformance(range)
      setState({
        status: 'loaded',
        range: data.range,
        periodStart: data.period_start,
        periodEnd: data.period_end,
        cumulativeTwr: data.cumulative_twr,
        isProvisional: data.is_provisional,
        points: data.points,
        error: null,
      })
    } catch (error) {
      setState({ ...IDLE, status: 'error', error })
    }
  }, [range])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
