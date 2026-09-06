import { useCallback, useState } from 'react'
import { adminCustomersApi } from '../api/adminCustomersApi.js'

const IDLE = { status: 'idle', query: '', results: [], error: null }

/** `status: 'idle'` means no query has been submitted yet — distinct from a submitted, empty-result search. */
export function useCustomerSearch() {
  const [state, setState] = useState(IDLE)

  const search = useCallback(async (query) => {
    setState((prev) => ({ ...prev, status: 'searching', query, error: null }))
    try {
      const results = await adminCustomersApi.search(query)
      setState({ status: 'loaded', query, results, error: null })
    } catch (error) {
      setState({ status: 'error', query, results: [], error })
    }
  }, [])

  return { ...state, search }
}
