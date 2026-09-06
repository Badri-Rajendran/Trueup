import { useCallback, useRef, useState } from 'react'
import { chatApi } from '../api/chatApi.js'

/** Exposes streaming text plus final structured trace separately (structure.md §5). Also owns the
 * `AbortController` behind a user-triggered stop: `stop()` aborts the in-flight fetch, and
 * `chatApi.streamMessage` treats that as a clean end of turn (not an error), so `status` always
 * settles back to `idle` rather than getting stuck in `streaming`. */
export function useChatStream(sessionId) {
  const [status, setStatus] = useState('idle')
  const [streamingText, setStreamingText] = useState('')
  const [error, setError] = useState(null)
  const controllerRef = useRef(null)

  const send = useCallback(
    async (text) => {
      const controller = new AbortController()
      controllerRef.current = controller
      setStatus('streaming')
      setStreamingText('')
      setError(null)
      try {
        const assistantMessage = await chatApi.streamMessage(sessionId, text, {
          onToken: setStreamingText,
          signal: controller.signal,
        })
        setStatus('idle')
        return assistantMessage
      } catch (err) {
        setError(err)
        setStatus('error')
        throw err
      } finally {
        controllerRef.current = null
      }
    },
    [sessionId],
  )

  const stop = useCallback(() => {
    controllerRef.current?.abort()
  }, [])

  return { status, streamingText, error, send, stop }
}
