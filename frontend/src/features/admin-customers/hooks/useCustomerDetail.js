import { useCallback, useEffect, useState } from 'react'
import { adminCustomersApi } from '../api/adminCustomersApi.js'

const IDLE = { status: 'idle', customer: null, error: null }

export function useCustomerDetail(customerId) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const customer = await adminCustomersApi.getDetail(customerId)
      if (customer === null) {
        setState({ status: 'error', customer: null, error: { code: 'not_found' } })
        return
      }
      setState({ status: 'loaded', customer, error: null })
    } catch (error) {
      setState({ status: 'error', customer: null, error })
    }
  }, [customerId])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
