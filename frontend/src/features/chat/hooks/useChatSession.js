import { useCallback, useEffect, useState } from 'react'
import { chatApi } from '../api/chatApi.js'

const IDLE = { status: 'idle', sessionId: null, messages: [], sessions: [], error: null }

/**
 * Owns "which session, what messages, what past sessions exist" as one piece of state
 * (frontend/CLAUDE.md: merge state that always changes together). On mount, resumes the most
 * recent session (`listSessions` is ordered newest-first by the backend --
 * `chat_session.py`'s `order_by(ChatSession.created_at.desc())`) instead of always starting a
 * blank one, so a conversation survives navigating away and back. `selectSession`/
 * `startNewSession` are the two explicit ways to change that from the session-history sidebar.
 */
export function useChatSession() {
  const [state, setState] = useState(IDLE)

  useEffect(() => {
    let cancelled = false

    async function resumeOrStart() {
      setState((prev) => ({ ...prev, status: 'loading' }))
      try {
        // A missing/failed history list shouldn't block the chat itself from working — fall back
        // to an empty list and just start a fresh session.
        const sessions = await chatApi.listSessions().catch(() => [])
        if (cancelled) return

        if (sessions.length > 0) {
          const mostRecent = sessions[0]
          const messages = await chatApi.getMessages(mostRecent.id)
          if (cancelled) return
          setState({ status: 'loaded', sessionId: mostRecent.id, messages, sessions, error: null })
          return
        }

        const session = await chatApi.createSession()
        if (cancelled) return
        setState({ status: 'loaded', sessionId: session.id, messages: [], sessions: [], error: null })
      } catch (error) {
        if (cancelled) return
        setState({ status: 'error', sessionId: null, messages: [], sessions: [], error })
      }
    }

    resumeOrStart()
    return () => {
      cancelled = true
    }
  }, [])

  const appendMessages = useCallback((newMessages) => {
    setState((prev) => ({ ...prev, messages: [...prev.messages, ...newMessages] }))
  }, [])

  const selectSession = useCallback(async (sessionId) => {
    setState((prev) => ({ ...prev, status: 'loading' }))
    try {
      const messages = await chatApi.getMessages(sessionId)
      setState((prev) => ({ ...prev, status: 'loaded', sessionId, messages, error: null }))
    } catch (error) {
      setState((prev) => ({ ...prev, status: 'error', error }))
    }
  }, [])

  const startNewSession = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading' }))
    try {
      const session = await chatApi.createSession()
      setState((prev) => ({
        ...prev,
        status: 'loaded',
        sessionId: session.id,
        messages: [],
        sessions: [{ id: session.id, status: 'idle', created_at: new Date().toISOString() }, ...prev.sessions],
        error: null,
      }))
    } catch (error) {
      setState((prev) => ({ ...prev, status: 'error', error }))
    }
  }, [])

  return { ...state, appendMessages, selectSession, startNewSession }
}
