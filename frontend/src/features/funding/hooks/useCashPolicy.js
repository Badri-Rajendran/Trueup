import { useCallback, useEffect, useState } from 'react'
import { fundingApi } from '../api/fundingApi.js'

const IDLE = { status: 'idle', withdrawable: null, investable: null, error: null }

// design-system.md §8.2
export function useCashPolicy() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await fundingApi.getCashSummary()
      setState({ status: 'loaded', withdrawable: data.withdrawable, investable: data.investable, error: null })
    } catch (error) {
      setState({ status: 'error', withdrawable: null, investable: null, error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
