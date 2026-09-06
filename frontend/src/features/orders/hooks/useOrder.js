import { useCallback, useEffect, useState } from 'react'
import { ordersApi } from '../api/ordersApi.js'

const IDLE = { status: 'idle', order: null, events: [], error: null }

export function useOrder(orderId) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await ordersApi.get(orderId)
      setState({ status: 'loaded', order: data.order, events: data.events, error: null })
    } catch (error) {
      setState({ status: 'error', order: null, events: [], error })
    }
  }, [orderId])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
