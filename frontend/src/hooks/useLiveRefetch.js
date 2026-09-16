import { useEffect } from 'react'
import { useEventStream } from '../contexts/EventStreamContext.jsx'

/** Re-runs `refetch` whenever a matching server-pushed event arrives (S12 §6). A subscribe/
 * unsubscribe primitive, not a data-fetch hook itself -- Tasks 8-12's own hooks call this
 * alongside their normal fetch/pagination logic. */
export function useLiveRefetch(eventTypes, refetch) {
  const { subscribe } = useEventStream()
  useEffect(() => subscribe(eventTypes, refetch), [subscribe, eventTypes, refetch])
}
