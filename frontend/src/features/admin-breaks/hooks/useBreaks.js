import { useCallback, useEffect, useState } from 'react'
import { useLiveRefetch } from '../../../hooks/useLiveRefetch.js'
import { adminBreaksApi } from '../api/adminBreaksApi.js'

const IDLE = { status: 'idle', breaks: [], error: null }

/** GET /admin/breaks?status=open, sorted oldest-first (S7 §7). */
export function useBreaks() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await adminBreaksApi.listOpen()
      setState({ status: 'loaded', breaks: data.breaks, error: null })
    } catch (error) {
      setState({ status: 'error', breaks: [], error })
    }
  }, [])

  useLiveRefetch(['break_opened'], refetch)

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
