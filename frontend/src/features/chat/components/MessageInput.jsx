import { useLayoutEffect, useRef, useState } from 'react'
import { Button } from '../../../components/Button'
import { Icon } from '../../../components/Icon'
import './MessageInput.css'

// Matches `content: str, max_length=4000` in backend/app/views/chat.py.
const MAX_LENGTH = 4000
// Counter only shows once the viewer is close enough to the cap that it's worth surfacing.
const COUNTER_THRESHOLD = 200
const MAX_TEXTAREA_HEIGHT_PX = 160

/**
 * `isStreaming` only swaps the button between Send and Stop — the field itself stays typeable
 * throughout, so composing a follow-up doesn't have to wait on the current reply. Submitting
 * while streaming is still a no-op client-side (the backend's own `chat_turn_in_progress` (409)
 * is the real constraint; there's no queue here yet, so the composed text just waits until the
 * viewer can send it once streaming ends).
 */
export function MessageInput({ onSend, onStop, isStreaming }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  // Auto-grow: reset to content height on every change, capped so a long message scrolls inside
  // the field instead of pushing the rest of the page around indefinitely.
  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`
  }, [text])

  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || isStreaming) return
    onSend(trimmed)
    setText('')
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    submit()
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const remaining = MAX_LENGTH - text.length
  const showCounter = remaining <= COUNTER_THRESHOLD

  return (
    <form className="tu-message-input" onSubmit={handleSubmit}>
      <div className="tu-message-input__field-wrap">
        <textarea
          ref={textareaRef}
          className="tu-message-input__field"
          aria-label="Message"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your account… (Enter to send, Shift+Enter for a new line)"
          maxLength={MAX_LENGTH}
          rows={1}
        />
        {showCounter && (
          <span
            className={`tu-message-input__counter${remaining <= 0 ? ' tu-message-input__counter--limit' : remaining <= 40 ? ' tu-message-input__counter--warning' : ''}`}
          >
            {Math.max(remaining, 0)} left
          </span>
        )}
      </div>
      {isStreaming ? (
        <Button type="button" variant="secondary" onClick={onStop}>
          <Icon name="stop" label="Stop generating" />
        </Button>
      ) : (
        <Button type="submit" disabled={!text.trim()}>
          <Icon name="send" label="Send message" />
        </Button>
      )}
    </form>
  )
}
