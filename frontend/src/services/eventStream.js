// Thin transport wrapper around the browser's native EventSource, for the server-sent event push
// added in S12 §6 (`GET /api/v1/events/stream`, `GET /api/v1/admin/events/stream`). Same category
// as apiClient.js/mockClient.js -- pure infra, knows nothing about orders/KYC/breaks. EventSource
// is a legitimate exception to "always use apiClient": it's a native browser streaming primitive,
// not a fetch call (the same exception category chatApi.js's raw-fetch SSE reader already is).
//
// The server frames every event as a plain `data: <json>\n\n` message with no `event:` line (see
// app/controllers/api/events.py), so the event type lives inside the JSON payload's `event_type`
// field rather than in EventSource's own named-event dispatch -- this listens on the generic
// `onmessage` and routes by that field itself. Heartbeats arrive as `: ping\n\n` comment lines,
// which EventSource never surfaces as a message at all.
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 30000

/**
 * Creates one independent EventSource-backed stream against `path`. Not exported as a bare
 * singleton -- `path` differs between the customer and admin variants (Task 12), so the shared
 * logic lives here and each caller (EventStreamContext) owns exactly one instance for its path.
 */
export function createEventStream(path) {
  let source = null
  let reconnectTimer = null
  let reconnectAttempts = 0
  let manuallyClosed = true
  let status = 'idle'
  const listenersByType = new Map()
  const statusListeners = new Set()

  function setStatus(next) {
    status = next
    for (const listener of statusListeners) listener(status)
  }

  function notify(eventType, payload) {
    const listeners = listenersByType.get(eventType)
    if (!listeners) return
    for (const listener of listeners) listener(payload)
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function scheduleReconnect() {
    if (manuallyClosed) return
    const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempts, RECONNECT_MAX_DELAY_MS)
    reconnectAttempts += 1
    reconnectTimer = setTimeout(open, delay)
  }

  function open() {
    clearReconnectTimer()
    setStatus('connecting')
    source = new EventSource(path)

    source.onopen = () => {
      reconnectAttempts = 0
      setStatus('open')
    }

    source.onmessage = (event) => {
      let payload
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      if (!payload?.event_type) return
      notify(payload.event_type, payload)
    }

    source.onerror = () => {
      // EventSource retries a dropped connection on its own by default. Only step in with our own
      // backoff once the browser has actually given up (readyState CLOSED) -- e.g. repeated
      // immediate failures -- rather than fighting its native retry for a transient blip.
      if (source?.readyState === EventSource.CLOSED) {
        setStatus('closed')
        scheduleReconnect()
      }
    }
  }

  return {
    connect() {
      manuallyClosed = false
      if (source) return
      open()
    },
    disconnect() {
      manuallyClosed = true
      clearReconnectTimer()
      reconnectAttempts = 0
      if (source) {
        source.close()
        source = null
      }
      setStatus('idle')
    },
    subscribe(eventTypes, listener) {
      for (const eventType of eventTypes) {
        if (!listenersByType.has(eventType)) listenersByType.set(eventType, new Set())
        listenersByType.get(eventType).add(listener)
      }
      return () => {
        for (const eventType of eventTypes) {
          listenersByType.get(eventType)?.delete(listener)
        }
      }
    },
    subscribeStatus(listener) {
      statusListeners.add(listener)
      return () => statusListeners.delete(listener)
    },
    getStatus() {
      return status
    },
  }
}

export const CUSTOMER_EVENT_STREAM_PATH = '/api/v1/events/stream'
export const ADMIN_EVENT_STREAM_PATH = '/api/v1/admin/events/stream'
