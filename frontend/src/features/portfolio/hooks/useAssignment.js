import { useCallback, useEffect, useState } from 'react'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = { status: 'idle', assignment: null, error: null }

// Separate states for GET and POST /portfolios/assignment; they don't change together.
export function useAssignment(customerId) {
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

  const assign = useCallback(
    async (modelId) => {
      setAssignStatus('submitting')
      setAssignError(null)
      try {
        const assignment = await portfoliosApi.assign(customerId, modelId)
        setState({ status: 'loaded', assignment, error: null })
        setAssignStatus('submitted')
        return assignment
      } catch (error) {
        setAssignError(error)
        setAssignStatus('error')
        throw error
      }
    },
    [customerId],
  )

  return { ...state, refetch, assign, assignStatus, assignError }
}
