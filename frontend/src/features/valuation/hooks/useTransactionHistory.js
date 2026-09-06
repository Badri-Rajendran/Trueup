import { useCallback, useEffect, useState } from 'react'
import { valuationApi } from '../api/valuationApi.js'

const IDLE = { status: 'idle', entries: [], error: null }

// ADR 6
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
