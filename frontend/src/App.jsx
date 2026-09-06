import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { SessionProvider, useSession } from './contexts/SessionContext.jsx'
import { AppLayout } from './pages/AppLayout.jsx'
import { BreakDetailPage } from './pages/admin/BreakDetailPage.jsx'
import { BreaksQueuePage } from './pages/admin/BreaksQueuePage.jsx'
import { FundingPage } from './pages/FundingPage.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { OnboardingPage } from './pages/OnboardingPage.jsx'
import { OrderDetailPage } from './pages/OrderDetailPage.jsx'
import { OrdersPage } from './pages/OrdersPage.jsx'
import { RegisterPage } from './pages/RegisterPage.jsx'
import { StatementDetailPage } from './pages/StatementDetailPage.jsx'
import { StatementsPage } from './pages/StatementsPage.jsx'
import { TransactionsPage } from './pages/TransactionsPage.jsx'
import { defaultRouteForPrincipal } from './routes/defaultRoute.js'
import { RequireAuth, RequireOnboarded, RequireRole } from './routes/guards.jsx'

const STAFF_ROLES = ['adviser', 'admin']

function defaultRouteFor(status, principal) {
  return status === 'authenticated' ? defaultRouteForPrincipal(principal) : '/login'
}

// Real routes land phase by phase (structure.md §2). Dashboard/portfolio/lots/fees/chat/admin-
// customers/statement-export are still to come — some need the Phase 4 mock domains.
function AppShell() {
  const { status, principal } = useSession()

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
        <Route
          path="/onboarding"
          element={
            <RequireRole roles={['customer']}>
              <OnboardingPage />
            </RequireRole>
          }
        />
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
          <Route path="/statements" element={<StatementsPage />} />
          <Route path="/statements/:periodStart" element={<StatementDetailPage />} />
        </Route>
        <Route
          element={
            <RequireRole roles={STAFF_ROLES}>
              <Outlet />
            </RequireRole>
          }
        >
          <Route path="/admin/breaks" element={<BreaksQueuePage />} />
          <Route path="/admin/breaks/:breakId" element={<BreakDetailPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={defaultRouteFor(status, principal)} replace />} />
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
