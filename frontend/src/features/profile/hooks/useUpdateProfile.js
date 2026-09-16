import { useCallback, useState } from 'react'
import { profileApi } from '../api/profileApi.js'

/**
 * `PATCH /profile`. `save`'s argument is already the exact partial-update body (ADR 27: a key
 * present-with-null clears that field, a key omitted leaves it unchanged) -- `ProfileForm` owns
 * deciding which keys belong in it, this hook just sends whatever it's given and surfaces the
 * result.
 */
export function useUpdateProfile() {
  const [status, setStatus] = useState('idle') // idle | submitting | submitted | error
  const [error, setError] = useState(null)

  const save = useCallback(async (patch) => {
    setStatus('submitting')
    setError(null)
    try {
      const profile = await profileApi.update(patch)
      setStatus('submitted')
      return profile
    } catch (err) {
      setStatus('error')
      setError(err)
      throw err
    }
  }, [])

  return { status, error, save }
}
