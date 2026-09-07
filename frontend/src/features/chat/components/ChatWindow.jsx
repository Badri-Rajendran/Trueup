import { useCallback, useEffect, useRef, useState } from 'react'
import { ErrorState } from '../../../components/ErrorState'
import { Icon } from '../../../components/Icon'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useChatSession } from '../hooks/useChatSession.js'
import { useChatStream } from '../hooks/useChatStream.js'
import { MessageInput } from './MessageInput.jsx'
import { MessageList } from './MessageList.jsx'
import { SessionHistory } from './SessionHistory.jsx'
import './ChatWindow.css'

// Only auto-scroll to the newest message when the viewer was already within this many pixels of
// the bottom — otherwise someone scrolled up to read history and a new token would yank them back.
const AUTO_SCROLL_THRESHOLD_PX = 96

export function ChatWindow() {
  const session = useChatSession()
  const stream = useChatStream(session.sessionId)
  const scrollRef = useRef(null)
  const stickToBottomRef = useRef(true)
  const [lastSentText, setLastSentText] = useState(null)
  const [historyOpen, setHistoryOpen] = useState(false)

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

  // A session switch must not carry over the previous session's stale streaming/error state.
  useEffect(() => {
    stream.reset()
  }, [session.sessionId, stream.reset])

  if (session.status === 'idle' || session.status === 'loading') {
    return <Skeleton height="300px" />
  }

  if (session.status === 'error') {
    return <ErrorState description={getErrorMessage(session.error)} />
  }

  const attemptSend = (text) => {
    stream
      .send(text)
      .then((assistantMessage) => {
        session.appendMessages([assistantMessage])
      })
      .catch(() => {})
    // Only a transport failure renders as an error here (FR-54) — a stopped stream resolves
    // normally with whatever text had already arrived, so it lands here too, not in .catch.
  }

  const handleSend = (text) => {
    stickToBottomRef.current = true
    setLastSentText(text)
    session.appendMessages([
      { id: `local-${Date.now()}`, role: 'user', text, created_at: new Date().toISOString() },
    ])
    attemptSend(text)
  }

  const handleRetry = () => {
    if (lastSentText) attemptSend(lastSentText)
  }

  const isStreaming = stream.status === 'streaming'

  return (
    <div className="tu-chat-window">
      <button
        type="button"
        className="tu-chat-window__history-toggle"
        aria-expanded={historyOpen}
        onClick={() => setHistoryOpen((prev) => !prev)}
      >
        <Icon name="history" size="sm" />
        {historyOpen ? 'Hide past conversations' : 'Past conversations'}
      </button>
      <div className="tu-chat-window__body">
        <SessionHistory
          sessions={session.sessions}
          activeSessionId={session.sessionId}
          onSelect={(id) => {
            session.selectSession(id)
            setHistoryOpen(false)
          }}
          onStartNew={() => {
            session.startNewSession()
            setHistoryOpen(false)
          }}
          disabled={isStreaming}
          open={historyOpen}
        />
        <div className="tu-chat-window__main">
          <div className="tu-chat-window__messages" ref={scrollRef} onScroll={handleScroll}>
            <MessageList
              messages={session.messages}
              streamingText={stream.streamingText}
              isStreaming={isStreaming}
              onSuggest={handleSend}
            />
            {stream.status === 'error' && (
              <ErrorState description={getErrorMessage(stream.error)} onRetry={handleRetry} />
            )}
          </div>
          <MessageInput onSend={handleSend} onStop={stream.stop} isStreaming={isStreaming} />
        </div>
      </div>
    </div>
  )
}
