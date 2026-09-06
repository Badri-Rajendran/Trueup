import { useCallback, useEffect, useState } from 'react'
import { feesApi } from '../api/feesApi.js'

const IDLE = { status: 'idle', accrual: null, charges: [], dunning: null, paymentMethod: null, error: null }

export function useFees() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await feesApi.get()
      setState({
        status: 'loaded',
        accrual: data.accrual,
        charges: data.charges,
        dunning: data.dunning,
        paymentMethod: data.payment_method,
        error: null,
      })
    } catch (error) {
      setState({ status: 'error', accrual: null, charges: [], dunning: null, paymentMethod: null, error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
