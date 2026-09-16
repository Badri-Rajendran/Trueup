import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { ADMIN_EVENT_STREAM_PATH, CUSTOMER_EVENT_STREAM_PATH, createEventStream } from '../services/eventStream.js'
import { useSession } from './SessionContext.jsx'

const EventStreamContext = createContext(undefined)

const STAFF_ROLES = ['adviser', 'admin']

/**
 * Owns the single live EventSource connection for whichever role is signed in -- the customer
 * channel (`customer:<id>:events`) or the adviser one (`adviser:events`, Task 12), never both.
 * Connects once `useSession()` reports `authenticated` and disconnects on logout or unmount, so a
 * signed-out tab never holds an open stream.
 */
export function EventStreamProvider({ children }) {
  const { status, principal } = useSession()
  const path = principal && STAFF_ROLES.includes(principal.role) ? ADMIN_EVENT_STREAM_PATH : CUSTOMER_EVENT_STREAM_PATH
  const stream = useMemo(() => createEventStream(path), [path])
  const [connectionStatus, setConnectionStatus] = useState(stream.getStatus())

  useEffect(() => {
    const unsubscribeStatus = stream.subscribeStatus(setConnectionStatus)
    if (status === 'authenticated') {
      stream.connect()
    }
    return () => {
      unsubscribeStatus()
      stream.disconnect()
    }
  }, [status, stream])

  const value = useMemo(
    () => ({ subscribe: stream.subscribe, connectionStatus }),
    [stream, connectionStatus],
  )

  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>
}

export function useEventStream() {
  const context = useContext(EventStreamContext)
  if (context === undefined) {
    throw new Error('useEventStream must be used within an EventStreamProvider')
  }
  return context
}
