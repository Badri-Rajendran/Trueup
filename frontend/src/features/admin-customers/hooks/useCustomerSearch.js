import { useCallback, useState } from 'react'
import { adminCustomersApi } from '../api/adminCustomersApi.js'

const IDLE = { status: 'idle', query: '', results: [], error: null }

/** idle = no query submitted yet, distinct from an empty result. */
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
