import { useCallback, useEffect, useState } from 'react'
import { useLiveRefetch } from '../../../hooks/useLiveRefetch.js'
import { ordersApi } from '../api/ordersApi.js'

const IDLE = { status: 'idle', orders: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'

export function useOrders() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await ordersApi.list()
      setState({ status: 'loaded', orders: data.orders, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', orders: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await ordersApi.list({ after: state.nextCursor })
      setState((prev) => ({
        status: 'loaded',
        orders: [...prev.orders, ...data.orders],
        nextCursor: data.next_cursor,
        error: null,
      }))
    } catch (error) {
      setState((prev) => ({ ...prev, status: 'error', error }))
    }
  }, [state.nextCursor, state.status])

  useLiveRefetch(['order_updated'], refetch)

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch, loadMore }
}
