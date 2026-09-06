import { useCallback, useState } from 'react'
import { mockClient } from '../../../services/mockClient.js'
import { chatApi } from '../api/chatApi.js'

/** Exposes streaming text plus the final structured trace separately (`structure.md` §5) — the mock reveals an already-resolved reply word-by-word rather than opening a real stream. */
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
        const assistantMessage = await chatApi.sendMessage(sessionId, text)
        const words = assistantMessage.text.split(' ')
        let revealed = ''
        for (const word of words) {
          revealed = revealed ? `${revealed} ${word}` : word
          setStreamingText(revealed)
          await mockClient.delay(60)
        }
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
