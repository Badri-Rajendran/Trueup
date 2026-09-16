const STORAGE_KEY = 'trueup.watchlist.v1'

function parseIds(raw) {
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) return []
  return parsed.filter((id) => typeof id === 'string')
}

/**
 * Watchlist membership lives entirely in `localStorage` — there is no backend list. Every read and
 * write is wrapped in try/catch so a private-mode or storage-disabled browser degrades to an empty
 * watchlist instead of throwing (task-8-brief.md).
 */
export const watchlistApi = {
  load() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      return raw ? parseIds(raw) : []
    } catch {
      return []
    }
  },
  save(securityIds) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(securityIds))
    } catch {
      // Storage unavailable, full, or private-mode — membership stays in-memory for this session.
    }
  },
}
