import { useCallback, useEffect, useRef } from 'react'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useChatSession } from '../hooks/useChatSession.js'
import { useChatStream } from '../hooks/useChatStream.js'
import { MessageInput } from './MessageInput.jsx'
import { MessageList } from './MessageList.jsx'
import './ChatWindow.css'

// Only auto-scroll to the newest message when the viewer was already within this many pixels of
// the bottom — otherwise someone scrolled up to read history and a new token would yank them back.
const AUTO_SCROLL_THRESHOLD_PX = 96

export function ChatWindow() {
  const session = useChatSession()
  const stream = useChatStream(session.sessionId)
  const scrollRef = useRef(null)
  const stickToBottomRef = useRef(true)

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottomRef.current = distanceFromBottom <= AUTO_SCROLL_THRESHOLD_PX
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !stickToBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [session.messages, stream.streamingText])

  if (session.status === 'idle' || session.status === 'loading') {
    return <Skeleton height="300px" />
  }

  if (session.status === 'error') {
    return <ErrorState description={getErrorMessage(session.error)} />
  }

  const handleSend = (text) => {
    stickToBottomRef.current = true
    session.appendMessages([
      { id: `local-${Date.now()}`, role: 'user', text, created_at: new Date().toISOString() },
    ])
    // Only a transport failure renders as an error here (FR-54) — a stopped stream resolves
    // normally with whatever text had already arrived, so it lands here too, not in .catch.
    stream
      .send(text)
      .then((assistantMessage) => {
        session.appendMessages([assistantMessage])
      })
      .catch(() => {})
  }

  return (
    <div className="tu-chat-window">
      <div className="tu-chat-window__messages" ref={scrollRef} onScroll={handleScroll}>
        <MessageList
          messages={session.messages}
          streamingText={stream.streamingText}
          isStreaming={stream.status === 'streaming'}
          onSuggest={handleSend}
        />
        {stream.status === 'error' && <ErrorState description={getErrorMessage(stream.error)} />}
      </div>
      <MessageInput
        onSend={handleSend}
        onStop={stream.stop}
        disabled={stream.status === 'streaming'}
      />
    </div>
  )
}
