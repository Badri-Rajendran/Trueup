import { useCallback, useEffect, useState } from 'react'
import { ordersApi } from '../api/ordersApi.js'

const IDLE = { status: 'idle', orders: [], error: null }

export function useOrders() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await ordersApi.list()
      setState({ status: 'loaded', orders: data.orders, error: null })
    } catch (error) {
      setState({ status: 'error', orders: [], error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
