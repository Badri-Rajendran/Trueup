import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { SessionProvider, useSession } from './contexts/SessionContext.jsx'
import { AppLayout } from './pages/AppLayout.jsx'
import { FundingPage } from './pages/FundingPage.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { OnboardingPage } from './pages/OnboardingPage.jsx'
import { OrderDetailPage } from './pages/OrderDetailPage.jsx'
import { OrdersPage } from './pages/OrdersPage.jsx'
import { RegisterPage } from './pages/RegisterPage.jsx'
import { TransactionsPage } from './pages/TransactionsPage.jsx'
import { RequireAuth, RequireOnboarded } from './routes/guards.jsx'

// Real routes land phase by phase (structure.md §2). Dashboard/portfolio/lots/statements/fees/chat/
// admin are still to come — some need the Phase 4 mock domains, some are later phases outright.
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
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route
          element={
            <RequireOnboarded>
              <Outlet />
            </RequireOnboarded>
          }
        >
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/orders/:orderId" element={<OrderDetailPage />} />
          <Route path="/transactions" element={<TransactionsPage />} />
          <Route path="/funding" element={<FundingPage />} />
        </Route>
      </Route>
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
