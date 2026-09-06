import { useCallback, useEffect, useState } from 'react'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = { status: 'idle', models: [], error: null }

export function useModels() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const models = await portfoliosApi.getModels()
      setState({ status: 'loaded', models, error: null })
    } catch (error) {
      setState({ status: 'error', models: [], error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
