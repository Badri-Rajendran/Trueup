import { ChatWindow } from '../features/chat/components/ChatWindow.jsx'
import './ChatPage.css'

export function ChatPage() {
  return (
    <div className="tu-chat-page">
      <div className="tu-chat-page__header">
        <h1 className="tu-chat-page__title">Ask Trueup</h1>
        <p className="tu-chat-page__subtitle">
          Ask about your balance, holdings, orders, and account activity.
        </p>
      </div>
      <div className="tu-chat-page__body">
        <ChatWindow />
      </div>
    </div>
  )
}
