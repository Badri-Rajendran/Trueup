import { useCallback, useEffect, useState } from 'react'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = { status: 'idle', assignment: null, error: null }

/** Covers both `GET /portfolios/assignment` (read) and `POST /portfolios/assignment` (assign) — the two lifecycles stay in separate merged states since they don't always change together. */
export function useAssignment() {
  const [state, setState] = useState(IDLE)
  const [assignStatus, setAssignStatus] = useState('idle')
  const [assignError, setAssignError] = useState(null)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const assignment = await portfoliosApi.getAssignment()
      setState({ status: 'loaded', assignment, error: null })
    } catch (error) {
      setState({ status: 'error', assignment: null, error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  const assign = useCallback(async (modelId) => {
    setAssignStatus('submitting')
    setAssignError(null)
    try {
      const assignment = await portfoliosApi.assign(modelId)
      setState({ status: 'loaded', assignment, error: null })
      setAssignStatus('submitted')
      return assignment
    } catch (error) {
      setAssignError(error)
      setAssignStatus('error')
      throw error
    }
  }, [])

  return { ...state, refetch, assign, assignStatus, assignError }
}
