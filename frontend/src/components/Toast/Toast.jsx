import { createContext, useCallback, useContext, useRef, useState } from 'react'
import './Toast.css'

const ToastContext = createContext(undefined)

let nextToastId = 0

/** Design system §7.8. Transient confirmations only — persistent state belongs in a row/banner (structure.md §6). */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismissToast = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const showToast = useCallback(
    ({ message, tone = 'neutral', persistent }) => {
      const id = ++nextToastId
      setToasts((current) => [...current, { id, message, tone }])

      const shouldPersist = persistent ?? tone === 'error'
      if (!shouldPersist) {
        const timer = setTimeout(() => dismissToast(id), 4000)
        timers.current.set(id, timer)
      }
      return id
    },
    [dismissToast],
  )

  return (
    <ToastContext.Provider value={{ showToast, dismissToast }}>
      {children}
      <div className="tu-toast-viewport" role="region" aria-label="Notifications">
        {toasts.map((toast) => (
          <div key={toast.id} className={`tu-toast tu-toast--${toast.tone}`} role="status">
            <span className="tu-toast__message">{toast.message}</span>
            <button
              type="button"
              className="tu-toast__dismiss"
              onClick={() => dismissToast(toast.id)}
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (context === undefined) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
