import { useCallback, useEffect, useState } from 'react'
import { statementsApi } from '../api/statementsApi.js'

const IDLE = { status: 'idle', statement: null, error: null }

export function useStatementDetail(periodStart, publishWatermark) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await statementsApi.get(periodStart, publishWatermark)
      setState({ status: 'loaded', statement: data, error: null })
    } catch (error) {
      setState({ status: 'error', statement: null, error })
    }
  }, [periodStart, publishWatermark])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
