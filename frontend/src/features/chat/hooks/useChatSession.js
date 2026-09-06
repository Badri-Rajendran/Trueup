import { useCallback, useEffect, useState } from 'react'
import { chatApi } from '../api/chatApi.js'

const IDLE = { status: 'idle', sessionId: null, messages: [], error: null }

export function useChatSession() {
  const [state, setState] = useState(IDLE)

  useEffect(() => {
    let cancelled = false

    async function start() {
      setState((prev) => ({ ...prev, status: 'loading' }))
      try {
        const session = await chatApi.createSession()
        if (cancelled) return
        setState({ status: 'loaded', sessionId: session.id, messages: [], error: null })
      } catch (error) {
        if (cancelled) return
        setState({ status: 'error', sessionId: null, messages: [], error })
      }
    }

    start()
    return () => {
      cancelled = true
    }
  }, [])

  const appendMessages = useCallback((newMessages) => {
    setState((prev) => ({ ...prev, messages: [...prev.messages, ...newMessages] }))
  }, [])

  return { ...state, appendMessages }
}
