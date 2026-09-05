import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { SessionProvider, useSession } from './contexts/SessionContext.jsx'

// Phase 0 foundation only — real routes (login, onboarding, dashboard, ...) land in Phase 1+.
// This shell exists so SessionContext, the router, and the toast system are wired and provable
// end to end before pages are built on top of them.
function AppShell() {
  const { status } = useSession()

  if (status === 'loading') {
    return null
  }

  return (
    <Routes>
      <Route path="*" element={<Navigate to={status === 'authenticated' ? '/dashboard' : '/login'} replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <ToastProvider>
          <AppShell />
        </ToastProvider>
      </SessionProvider>
    </BrowserRouter>
  )
}
