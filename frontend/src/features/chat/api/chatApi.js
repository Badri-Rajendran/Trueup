// MOCK — no backend endpoint exists yet (S11 NL query assistant). Replace with a real fetch call
// once that spec ships. The real `POST /chat/sessions/:id/messages` is `text/event-stream`
// (`structure.md` §5) — this build has no SSE at all (Phase 0 scope decision), so the mock
// resolves the full reply and `useChatStream` simulates the token reveal client-side instead.
import { mockClient } from '../../../services/mockClient.js'

const NAMESPACE = 'chat'

function seed() {
  return { sessions: [] }
}

function cannedReply(text) {
  const lower = text.toLowerCase()
  if (lower.includes('balance')) {
    return {
      text: 'Your account balance is $52,000.00 as of the latest close.',
      tool_calls: [{ tool: 'get_balance', arguments: {}, result: '{"total_value": "52000.00"}' }],
    }
  }
  if (lower.includes('return') || lower.includes('performance')) {
    return {
      text: 'Your month-to-date return is +2.35%.',
      tool_calls: [{ tool: 'get_returns', arguments: { period: 'mtd' }, result: '{"twr": "0.0235"}' }],
    }
  }
  // FR-54: a decline-to-answer renders as a normal assistant message, not an error.
  return {
    text: "I'm not able to help with that yet — try asking about your balance or recent returns.",
    tool_calls: [],
  }
}

export const chatApi = {
  createSession: () => {
    const store = mockClient.getStore(NAMESPACE, seed)
    const session = { id: mockClient.mockId(NAMESPACE, store.sessions.length + 1), created_at: new Date().toISOString(), messages: [] }
    store.sessions.push(session)
    return mockClient.request({ id: session.id, created_at: session.created_at })
  },
  listSessions: () => {
    const store = mockClient.getStore(NAMESPACE, seed)
    return mockClient.request(store.sessions.map(({ id, created_at }) => ({ id, created_at })))
  },
  getMessages: (sessionId) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    const session = store.sessions.find((candidate) => candidate.id === sessionId)
    return mockClient.request(session ? session.messages : [])
  },
  sendMessage: (sessionId, text) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    const session = store.sessions.find((candidate) => candidate.id === sessionId)
    const reply = cannedReply(text)
    const userMessage = {
      id: mockClient.mockId(NAMESPACE, `${sessionId}-u-${session.messages.length}`),
      role: 'user',
      text,
      created_at: new Date().toISOString(),
    }
    const assistantMessage = {
      id: mockClient.mockId(NAMESPACE, `${sessionId}-a-${session.messages.length + 1}`),
      role: 'assistant',
      text: reply.text,
      tool_calls: reply.tool_calls,
      created_at: new Date().toISOString(),
    }
    session.messages.push(userMessage, assistantMessage)
    return mockClient.request(assistantMessage, { latency: 500 })
  },
}
