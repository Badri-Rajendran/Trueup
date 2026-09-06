import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useChatSession } from '../hooks/useChatSession.js'
import { useChatStream } from '../hooks/useChatStream.js'
import { MessageInput } from './MessageInput.jsx'
import { MessageList } from './MessageList.jsx'
import './ChatWindow.css'

export function ChatWindow() {
  const session = useChatSession()
  const stream = useChatStream(session.sessionId)

  if (session.status === 'idle' || session.status === 'loading') {
    return <Skeleton height="300px" />
  }

  if (session.status === 'error') {
    return <ErrorState description={getErrorMessage(session.error)} />
  }

  const handleSend = (text) => {
    session.appendMessages([{ id: `local-${Date.now()}`, role: 'user', text }])
    // A genuine transport failure is the only thing that renders as an error here (FR-54) — a
    // decline-to-answer is already just a normal assistant message from the mock's own reply.
    stream.send(text).then((assistantMessage) => {
      session.appendMessages([assistantMessage])
    }).catch(() => {})
  }

  return (
    <div className="tu-chat-window">
      <div className="tu-chat-window__messages">
        <MessageList
          messages={session.messages}
          streamingText={stream.streamingText}
          isStreaming={stream.status === 'streaming'}
          onSuggest={handleSend}
        />
        {stream.status === 'error' && <ErrorState description={getErrorMessage(stream.error)} />}
      </div>
      <MessageInput onSend={handleSend} disabled={stream.status === 'streaming'} />
    </div>
  )
}
