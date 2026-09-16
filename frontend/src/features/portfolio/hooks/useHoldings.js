import { useCallback, useEffect, useState } from 'react'
import { useLiveRefetch } from '../../../hooks/useLiveRefetch.js'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = {
  status: 'idle',
  asOfDate: null,
  completeness: null,
  totalValue: null,
  holdings: [],
  error: null,
}
// status: 'idle' | 'loading' | 'loaded' | 'unassigned' | 'error'

/**
 * `GET /portfolios/holdings` (Dashboard, task-8-brief.md). A 404 with `code: "no_model_assigned"`
 * is not a fetch failure — it means the customer hasn't chosen a model yet, so it maps to a
 * distinct `unassigned` status rather than `error`; the owning component renders `AssignmentPrompt`
 * for that case, never `ErrorState`.
 */
export function useHoldings() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await portfoliosApi.getHoldings()
      setState({
        status: 'loaded',
        asOfDate: data.as_of_date,
        completeness: data.completeness,
        totalValue: data.total_value,
        holdings: data.holdings,
        error: null,
      })
    } catch (error) {
      if (error.code === 'no_model_assigned') {
        setState({ ...IDLE, status: 'unassigned' })
        return
      }
      setState({ ...IDLE, status: 'error', error })
    }
  }, [])

  useLiveRefetch(['order_updated'], refetch)

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
