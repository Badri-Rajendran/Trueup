import { useCallback, useEffect, useState } from 'react'
import { fundingApi } from '../api/fundingApi.js'

const IDLE = { status: 'idle', bankLink: null, error: null }

/** `GET /funding/bank-links/current` — the only way to know "is a bank already linked" at all. */
export function useCurrentBankLink() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await fundingApi.getCurrentBankLink()
      setState({ status: 'loaded', bankLink: data.bank_link, error: null })
    } catch (error) {
      setState({ status: 'error', bankLink: null, error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
