import { useCallback, useEffect, useState } from 'react'
import { valuationApi } from '../api/valuationApi.js'

const IDLE = { status: 'idle', twr: null, isProvisional: false, error: null }

// periodStart/periodEnd are ISO 8601 datetime strings, not just date.
export function useReturns(periodStart, periodEnd) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await valuationApi.getReturns(periodStart, periodEnd)
      setState({ status: 'loaded', twr: data.twr, isProvisional: data.is_provisional, error: null })
    } catch (error) {
      setState({ status: 'error', twr: null, isProvisional: false, error })
    }
  }, [periodStart, periodEnd])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
