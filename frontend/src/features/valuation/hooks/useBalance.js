import { useCallback, useEffect, useState } from 'react'
import { valuationApi } from '../api/valuationApi.js'

const IDLE = { status: 'idle', totalValue: null, asOfDate: null, completeness: null, error: null }

export function useBalance() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await valuationApi.getBalance()
      setState({
        status: 'loaded',
        totalValue: data.total_value,
        asOfDate: data.as_of_date,
        completeness: data.completeness,
        error: null,
      })
    } catch (error) {
      setState({ status: 'error', totalValue: null, asOfDate: null, completeness: null, error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
