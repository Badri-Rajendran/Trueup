// S11 NL query assistant — POST/GET /chat/sessions, GET/POST /chat/sessions/:id/messages.
// The send endpoint is `text/event-stream`, so it goes through a raw `fetch` + `ReadableStream`
// reader rather than `apiClient` (which only ever does `response.json()`).
import { apiClient, ApiError } from '../../../services/apiClient.js'

const API_BASE = '/api/v1'

function toMessage({ id, role, content, created_at }) {
  return { id, role, text: content, created_at }
}

async function parseErrorBody(response) {
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('json')) return null
  try {
    return await response.json()
  } catch {
    return null
  }
}

export const chatApi = {
  createSession: async () => {
    const data = await apiClient.post('/chat/sessions')
    return { id: data.session_id }
  },
  listSessions: async () => {
    const data = await apiClient.get('/chat/sessions')
    return data.sessions
  },
  getMessages: async (sessionId) => {
    const data = await apiClient.get(`/chat/sessions/${sessionId}/messages`)
    return data.messages.map(toMessage)
  },
  /** Streams the assistant's reply, calling `onToken(accumulatedText)` as each token frame
   * arrives, and resolving with the final assistant message once the `completed` frame lands. */
  streamMessage: async (sessionId, text, { onToken } = {}) => {
    let response
    try {
      response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          'X-CSRFToken': apiClient.getCsrfToken(),
        },
        body: JSON.stringify({ content: text }),
      })
    } catch {
      throw new ApiError({ status: 0, code: 'network_error', title: 'Network request failed' })
    }

    if (!response.ok) {
      const data = await parseErrorBody(response)
      throw new ApiError({
        status: response.status,
        code: data?.code,
        title: data?.title,
        type: data?.type,
        correlationId: data?.correlation_id,
      })
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let accumulator = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let separatorIndex
      // eslint-disable-next-line no-cond-assign
      while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, separatorIndex)
        buffer = buffer.slice(separatorIndex + 2)

        const dataLine = rawEvent.split('\n').find((line) => line.startsWith('data:'))
        if (!dataLine) continue
        const frame = JSON.parse(dataLine.slice('data:'.length).trim())

        if (frame.type === 'token') {
          accumulator += frame.text
          onToken?.(accumulator)
        } else if (frame.type === 'completed') {
          return {
            id: frame.message_id,
            role: 'assistant',
            text: accumulator,
            tool_calls: frame.tool_calls,
          }
        } else if (frame.type === 'error') {
          throw new Error(frame.message)
        }
      }
    }

    return { id: `local-${Date.now()}`, role: 'assistant', text: accumulator, tool_calls: [] }
  },
}
