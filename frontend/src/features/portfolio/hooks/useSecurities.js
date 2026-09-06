import { useCallback, useEffect, useState } from 'react'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = { status: 'idle', securities: [], error: null }

/** The orderable universe — consumed cross-feature by `orders`' OrderForm (mock-data owner stays `portfolio`). */
export function useSecurities() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const securities = await portfoliosApi.getSecurities()
      setState({ status: 'loaded', securities, error: null })
    } catch (error) {
      setState({ status: 'error', securities: [], error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
