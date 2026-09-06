import { useCallback, useEffect, useState } from 'react'
import { statementsApi } from '../api/statementsApi.js'
import { groupStatementsByPeriod } from '../groupStatementsByPeriod.js'

const IDLE = { status: 'idle', periods: [], error: null }

export function useStatements() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await statementsApi.list()
      setState({ status: 'loaded', periods: groupStatementsByPeriod(data.statements), error: null })
    } catch (error) {
      setState({ status: 'error', periods: [], error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
