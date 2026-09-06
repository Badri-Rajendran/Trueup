import { EmptyState } from '../../../components/EmptyState'
import { ToolTraceDisclosure } from './ToolTraceDisclosure.jsx'
import './MessageList.css'

const SUGGESTED_QUESTIONS = ['What is my account balance?', 'What is my month-to-date return?']

export function MessageList({ messages, streamingText, isStreaming, onSuggest }) {
  if (messages.length === 0 && !isStreaming) {
    return (
      <EmptyState
        title="Ask about your account"
        description="Try a question like one of these."
        action={
          <div className="tu-message-list__suggestions">
            {SUGGESTED_QUESTIONS.map((question) => (
              <button key={question} type="button" className="tu-message-list__suggestion" onClick={() => onSuggest?.(question)}>
                {question}
              </button>
            ))}
          </div>
        }
      />
    )
  }

  return (
    <div className="tu-message-list">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`tu-message-list__bubble ${message.role === 'user' ? 'tu-message-list__bubble--user' : 'tu-message-list__bubble--assistant'}`}
        >
          {message.text}
          {message.role === 'assistant' && <ToolTraceDisclosure toolCalls={message.tool_calls} />}
        </div>
      ))}
      {isStreaming && (
        <div className="tu-message-list__bubble tu-message-list__bubble--assistant">
          {streamingText || (
            <span className="tu-message-list__typing" aria-label="Assistant is typing">
              <span />
              <span />
              <span />
            </span>
          )}
        </div>
      )}
    </div>
  )
}
