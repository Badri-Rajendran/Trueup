import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { SessionProvider, useSession } from './contexts/SessionContext.jsx'
import { AppLayout } from './pages/AppLayout.jsx'
import { BreakDetailPage } from './pages/admin/BreakDetailPage.jsx'
import { BreaksQueuePage } from './pages/admin/BreaksQueuePage.jsx'
import { CustomerDetailPage } from './pages/admin/CustomerDetailPage.jsx'
import { CustomerDirectoryPage } from './pages/admin/CustomerDirectoryPage.jsx'
import { ChatPage } from './pages/ChatPage.jsx'
import { DashboardPage } from './pages/DashboardPage.jsx'
import { FeesPage } from './pages/FeesPage.jsx'
import { FundingPage } from './pages/FundingPage.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { LotsPage } from './pages/LotsPage.jsx'
import { OnboardingPage } from './pages/OnboardingPage.jsx'
import { OrderDetailPage } from './pages/OrderDetailPage.jsx'
import { OrderNewPage } from './pages/OrderNewPage.jsx'
import { OrdersPage } from './pages/OrdersPage.jsx'
import { PortfolioPage } from './pages/PortfolioPage.jsx'
import { RegisterPage } from './pages/RegisterPage.jsx'
import { StatementDetailPage } from './pages/StatementDetailPage.jsx'
import { StatementsPage } from './pages/StatementsPage.jsx'
import { defaultRouteForPrincipal } from './routes/defaultRoute.js'
import { RequireAuth, RequireOnboarded, RequireRole } from './routes/guards.jsx'

const STAFF_ROLES = ['adviser', 'admin']

function defaultRouteFor(status, principal) {
  return status === 'authenticated' ? defaultRouteForPrincipal(principal) : '/login'
}

// Every route in structure.md §2 is real; some are backed by a mock adapter, not a live endpoint.
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
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/orders/new" element={<OrderNewPage />} />
          <Route path="/orders/:orderId" element={<OrderDetailPage />} />
          <Route path="/funding" element={<FundingPage />} />
          <Route path="/lots" element={<LotsPage />} />
          <Route path="/statements" element={<StatementsPage />} />
          <Route path="/statements/:periodStart" element={<StatementDetailPage />} />
          <Route path="/fees" element={<FeesPage />} />
          <Route path="/chat" element={<ChatPage />} />
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
          <Route path="/admin/customers" element={<CustomerDirectoryPage />} />
          <Route path="/admin/customers/:customerId" element={<CustomerDetailPage />} />
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
