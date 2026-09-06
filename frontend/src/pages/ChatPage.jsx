import { ChatWindow } from '../features/chat/components/ChatWindow.jsx'
import './PageLayout.css'

export function ChatPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Ask Trueup</h1>
      <ChatWindow />
    </div>
  )
}
