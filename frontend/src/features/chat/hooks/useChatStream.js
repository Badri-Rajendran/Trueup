import { useCallback, useState } from 'react'
import { chatApi } from '../api/chatApi.js'

/** Exposes streaming text plus the final structured trace separately (`structure.md` §5) — tokens
 * arrive from the real SSE stream via `chatApi.streamMessage`'s `onToken` callback. */
export function useChatStream(sessionId) {
  const [status, setStatus] = useState('idle')
  const [streamingText, setStreamingText] = useState('')
  const [error, setError] = useState(null)

  const send = useCallback(
    async (text) => {
      setStatus('streaming')
      setStreamingText('')
      setError(null)
      try {
        const assistantMessage = await chatApi.streamMessage(sessionId, text, {
          onToken: setStreamingText,
        })
        setStatus('idle')
        return assistantMessage
      } catch (err) {
        setError(err)
        setStatus('error')
        throw err
      }
    },
    [sessionId],
  )

  return { status, streamingText, error, send }
}
