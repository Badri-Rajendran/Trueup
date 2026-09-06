import { useCallback, useEffect, useState } from 'react'
import { lotsApi } from '../api/lotsApi.js'

const IDLE = { status: 'idle', lots: [], error: null }

export function useLots() {
  const [state, setState] = useState(IDLE)

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

  return { ...state, refetch }
}
