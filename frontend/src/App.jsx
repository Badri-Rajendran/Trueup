import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { ToastProvider } from './components/Toast'
import { SessionProvider, useSession } from './contexts/SessionContext.jsx'
import { AccountPage } from './pages/AccountPage.jsx'
import { AppLayout } from './pages/AppLayout.jsx'
import { BreakDetailPage } from './pages/admin/BreakDetailPage.jsx'
import { BreaksQueuePage } from './pages/admin/BreaksQueuePage.jsx'
import { CustomerDetailPage } from './pages/admin/CustomerDetailPage.jsx'
import { CustomerDirectoryPage } from './pages/admin/CustomerDirectoryPage.jsx'
import { ChatPage } from './pages/ChatPage.jsx'
import { DashboardPage } from './pages/DashboardPage.jsx'
import { InvestPage } from './pages/InvestPage.jsx'
import { LoginPage } from './pages/LoginPage.jsx'
import { MoneyPage } from './pages/MoneyPage.jsx'
import { OnboardingPage } from './pages/OnboardingPage.jsx'
import { OrderDetailPage } from './pages/OrderDetailPage.jsx'
import { OrderNewPage } from './pages/OrderNewPage.jsx'
import { RegisterPage } from './pages/RegisterPage.jsx'
import { StatementDetailPage } from './pages/StatementDetailPage.jsx'
import { defaultRouteForPrincipal } from './routes/defaultRoute.js'
import { RequireAuth, RequireOnboarded, RequireRole } from './routes/guards.jsx'

const STAFF_ROLES = ['adviser', 'admin']

function defaultRouteFor(status, principal) {
  return status === 'authenticated' ? defaultRouteForPrincipal(principal) : '/login'
}

/** Preserves the id when redirecting the old `/orders/:orderId` bookmark to its new home --
 * a bare `<Navigate to="/invest">` would drop the id and strand the visitor on the list. */
function OrderDetailRedirect() {
  const { orderId } = useParams()
  return <Navigate to={`/invest/orders/${orderId}`} replace />
}

/** Same trick as `OrderDetailRedirect`, plus the search string: a restated period's "View
 * original as-published statement" link carries a `?publish_watermark=` query param that a bare
 * `<Navigate>` would otherwise drop, stranding that old bookmark on the current (not original)
 * figures. */
function StatementDetailRedirect() {
  const { periodStart } = useParams()
  const location = useLocation()
  return <Navigate to={`/account/statements/${periodStart}${location.search}`} replace />
}

// Every route in structure.md §2 is real; some are backed by a mock adapter, not a live endpoint.
//
// The 10 former customer routes collapse into 5 nav destinations (structure.md §2, Task 7).
// /invest is InvestPage (Task 9) -- PortfolioPage/OrdersPage/LotsPage folded into one, with
// /invest/orders/new and /invest/orders/:orderId as real sub-routes (restyled, not rebuilt).
// /money is MoneyPage (Task 10) -- the old FundingPage and (previously unrouted) FeesPage folded
// into one destination. /account is AccountPage (Task 11) -- profile (net-new), both identity
// gates, bank link, and statements, with /account/statements/:periodStart as its own real
// sub-route (StatementDetailPage, restyled not rebuilt).
function AppShell() {
  const { status, principal } = useSession()

  if (status === 'loading') {
    return null
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Old paths -> new destination, so existing bookmarks/links don't 404. Each target route
          re-applies its own guards on the follow-up render (e.g. an anonymous visitor still ends
          up at /login), exactly as hitting the old path directly did before. `/orders/new`,
          `/orders/:orderId`, and `/statements/:periodStart` get their own redirect (not a blanket
          `/orders/*`/`/statements/*`) so the id (and, for statements, the `publish_watermark`
          query param) survives the trip -- a bare `/invest`/`/account` would otherwise strand an
          old bookmark on the list with no way back to the specific thing it named. `/lots` now
          redirects to `/invest` (Task 9 folded `LotsPage` into `InvestPage`), not `/money`.
          `/statements` (bare, no period) redirects to `/account`, not `/money` -- statements moved
          there in Task 11's IA (Money = funding+fees only; Account = profile+identity+bank-
          link+statements). */}
      <Route path="/portfolio" element={<Navigate to="/invest" replace />} />
      <Route path="/orders" element={<Navigate to="/invest" replace />} />
      <Route path="/orders/new" element={<Navigate to="/invest/orders/new" replace />} />
      <Route path="/orders/:orderId" element={<OrderDetailRedirect />} />
      <Route path="/funding" element={<Navigate to="/money" replace />} />
      <Route path="/lots" element={<Navigate to="/invest" replace />} />
      <Route path="/statements" element={<Navigate to="/account" replace />} />
      <Route path="/statements/:periodStart" element={<StatementDetailRedirect />} />
      <Route path="/fees/*" element={<Navigate to="/money" replace />} />

      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        {/* /onboarding is a sibling OUTSIDE RequireOnboarded, guarded only by role -- nesting it
            inside RequireOnboarded would be an infinite redirect loop (the guard fails closed,
            redirects here, and immediately fails closed again). */}
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
          <Route path="/invest" element={<InvestPage />} />
          <Route path="/invest/orders/new" element={<OrderNewPage />} />
          <Route path="/invest/orders/:orderId" element={<OrderDetailPage />} />
          <Route path="/money" element={<MoneyPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/account/statements/:periodStart" element={<StatementDetailPage />} />
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
