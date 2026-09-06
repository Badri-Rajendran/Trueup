import { useCallback, useEffect, useState } from 'react'
import { valuationApi } from '../api/valuationApi.js'

const IDLE = { status: 'idle', entries: [], error: null }

/** `GET /valuation/history` — live by default (ADR 6); S6 owns the as-published statement variant. */
export function useTransactionHistory() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await valuationApi.getHistory()
      setState({ status: 'loaded', entries: data.entries, error: null })
    } catch (error) {
      setState({ status: 'error', entries: [], error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
