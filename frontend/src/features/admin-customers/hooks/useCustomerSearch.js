import { useCallback, useState } from 'react'
import { adminCustomersApi } from '../api/adminCustomersApi.js'

const IDLE = { status: 'idle', query: '', customers: [], nextCursor: null, error: null }
// status: 'idle' | 'searching' | 'loaded' | 'loading-more' | 'error'

/** idle = no query submitted yet, distinct from an empty result. The backend rejects a blank
 * `query` (422) -- rather than round-trip for that, a blank/whitespace-only query resolves to an
 * empty result locally, same as the old mock's behaviour. */
export function useCustomerSearch() {
  const [state, setState] = useState(IDLE)

  const search = useCallback(async (query) => {
    const trimmed = query.trim()
    if (!trimmed) {
      setState({ status: 'loaded', query, customers: [], nextCursor: null, error: null })
      return
    }
    setState((prev) => ({ ...prev, status: 'searching', query, error: null }))
    try {
      const data = await adminCustomersApi.search(trimmed)
      setState({ status: 'loaded', query, customers: data.customers, nextCursor: data.next_cursor, error: null })
    } catch (error) {
      setState({ status: 'error', query, customers: [], nextCursor: null, error })
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (state.nextCursor === null || state.status === 'loading-more') return
    setState((prev) => ({ ...prev, status: 'loading-more' }))
    try {
      const data = await adminCustomersApi.search(state.query.trim(), { after: state.nextCursor })
      setState((prev) => ({
        status: 'loaded',
        query: prev.query,
        customers: [...prev.customers, ...data.customers],
        nextCursor: data.next_cursor,
        error: null,
      }))
    } catch (error) {
      setState((prev) => ({ ...prev, status: 'error', error }))
    }
  }, [state.query, state.nextCursor, state.status])

  return { ...state, search, loadMore }
}
