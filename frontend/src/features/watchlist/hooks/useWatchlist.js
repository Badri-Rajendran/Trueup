import { useCallback, useState } from 'react'
import { watchlistApi } from '../api/watchlistApi.js'

/**
 * Watchlist membership (an array of `security_id`), persisted to `localStorage`. Purely local,
 * synchronous state — no network call, so there is no `status` fetch machine here. Pricing for the
 * watched securities is a separate concern (`useSecurities`) that `WatchlistPanel` composes this
 * hook with.
 */
export function useWatchlist() {
  const [securityIds, setSecurityIds] = useState(watchlistApi.load)

  const add = useCallback((securityId) => {
    setSecurityIds((prev) => {
      if (prev.includes(securityId)) return prev
      const next = [...prev, securityId]
      watchlistApi.save(next)
      return next
    })
  }, [])

  const remove = useCallback((securityId) => {
    setSecurityIds((prev) => {
      const next = prev.filter((id) => id !== securityId)
      watchlistApi.save(next)
      return next
    })
  }, [])

  return { securityIds, add, remove }
}
