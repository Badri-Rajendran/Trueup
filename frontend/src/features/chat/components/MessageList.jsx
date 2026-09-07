import { EmptyState } from '../../../components/EmptyState'
import { formatDateTime } from '../../../utils/format.js'
import { renderMarkdown } from '../utils/renderMarkdown.jsx'
import { ToolTraceDisclosure } from './ToolTraceDisclosure.jsx'
import './MessageList.css'

// A handful of real questions the app actually has data for (balance, returns, holdings, orders,
// tax lots, funding) — never a feature this build doesn't have.
const SUGGESTED_QUESTIONS = [
  'What is my account balance?',
  'What is my month-to-date return?',
  'What are my current holdings?',
  'Do I have any orders awaiting approval?',
  'What tax lots do I own?',
  'When did my last deposit settle?',
]

function AssistantAvatar() {
  // Reuses the wordmark's own serif letterform as the assistant's identity mark — a small,
  // on-brand monogram, not a generic bot icon.
  return (
    <span className="tu-message-list__avatar" aria-hidden="true">
      T
    </span>
  )
}

export function MessageList({ messages, streamingText, isStreaming, onSuggest }) {
  if (messages.length === 0 && !isStreaming) {
    return (
      <EmptyState
        title="What would you like to know?"
        description="Try one of these, or type your own question below."
        action={
          <div className="tu-message-list__suggestions">
            {SUGGESTED_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                className="tu-suggestion-chip"
                onClick={() => onSuggest?.(question)}
              >
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
      {messages.map((message) =>
        message.role === 'user' ? (
          <div key={message.id} className="tu-message-list__turn tu-message-list__turn--user">
            <div className="tu-message-list__bubble">
              <div className="tu-message-list__text">{message.text}</div>
            </div>
            {message.created_at && (
              <span className="tu-message-list__timestamp">{formatDateTime(message.created_at)}</span>
            )}
          </div>
        ) : (
          <div key={message.id} className="tu-message-list__turn tu-message-list__turn--assistant">
            <AssistantAvatar />
            <div className="tu-message-list__content">
              <div className="tu-message-list__text">{renderMarkdown(message.text)}</div>
              {message.created_at && (
                <span className="tu-message-list__timestamp">{formatDateTime(message.created_at)}</span>
              )}
              <ToolTraceDisclosure toolCalls={message.tool_calls} />
            </div>
          </div>
        ),
      )}
      {isStreaming && (
        <div className="tu-message-list__turn tu-message-list__turn--assistant">
          <AssistantAvatar />
          <div className="tu-message-list__content">
            {streamingText ? (
              // aria-atomic="false": only the newly-appended text is announced as it streams in,
              // rather than re-reading the whole growing reply on every token.
              <div className="tu-message-list__text" aria-live="polite" aria-atomic="false">
                {renderMarkdown(streamingText)}
              </div>
            ) : (
              // No SSE frame tells the client a tool call has started mid-stream (only the terminal
              // `completed` event carries `tool_calls`), so this can only honestly say the reply is
              // pending — never claim "checking your account" when that's not something we know yet.
              <span className="tu-message-list__typing" aria-label="Trueup is working on a reply">
                <span />
                <span />
                <span />
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
