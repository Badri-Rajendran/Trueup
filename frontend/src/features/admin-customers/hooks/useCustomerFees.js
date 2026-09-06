import { useCallback, useEffect, useState } from 'react'
import { feesApi } from '../../fees/api/feesApi.js'

const IDLE = { status: 'idle', accrual: null, dunning: null, error: null }

export function useCustomerFees(customerId) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await feesApi.getForCustomer(customerId)
      setState({ status: 'loaded', accrual: data.accrual, dunning: data.dunning, error: null })
    } catch (error) {
      setState({ status: 'error', accrual: null, dunning: null, error })
    }
  }, [customerId])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
