import { useState } from 'react'
import { Button } from '../../../components/Button'
import './MessageInput.css'

export function MessageInput({ onSend, disabled, value }) {
  const [text, setText] = useState(value || '')

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!text.trim() || disabled) return
    onSend(text.trim())
    setText('')
  }

  return (
    <form className="tu-message-input" onSubmit={handleSubmit}>
      <input
        className="tu-message-input__field"
        type="text"
        aria-label="Message"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Ask about your account…"
        disabled={disabled}
      />
      <Button type="submit" disabled={disabled || !text.trim()}>
        Send
      </Button>
    </form>
  )
}
