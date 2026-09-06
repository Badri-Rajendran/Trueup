import { useCallback, useState } from 'react'
import { adminBreaksApi } from '../api/adminBreaksApi.js'

export function useResolveBreak() {
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const resolve = useCallback(async (breakId, resolutionNote) => {
    setStatus('submitting')
    setError(null)
    try {
      const data = await adminBreaksApi.resolve(breakId, resolutionNote)
      setStatus('submitted')
      return data
    } catch (err) {
      setError(err)
      setStatus('error')
      throw err
    }
  }, [])

  return { status, error, resolve }
}
