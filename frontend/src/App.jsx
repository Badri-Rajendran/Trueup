import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { SessionProvider, useSession } from './contexts/SessionContext.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { OnboardingPage } from './pages/OnboardingPage.jsx'
import { RegisterPage } from './pages/RegisterPage.jsx'
import { RequireAuth } from './routes/guards.jsx'

// Real routes land phase by phase (structure.md §2) — dashboard/portfolio/orders/etc. are Phase 2+.
// Once authenticated, everything unmatched lands on /onboarding for now since it's the only
// customer-app screen that exists yet.
function AppShell() {
  const { status } = useSession()

  if (status === 'loading') {
    return null
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/onboarding"
        element={
          <RequireAuth>
            <OnboardingPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to={status === 'authenticated' ? '/onboarding' : '/login'} replace />} />
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
