import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useSession } from '../contexts/SessionContext.jsx'
import './AppLayout.css'

const CUSTOMER_NAV_LINKS = [
  { to: '/onboarding', label: 'Onboarding' },
  { to: '/orders', label: 'Orders' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/funding', label: 'Funding' },
  { to: '/statements', label: 'Statements' },
]

const STAFF_NAV_LINKS = [{ to: '/admin/breaks', label: 'Reconciliation breaks' }]

function navLinkClassName({ isActive }) {
  return isActive ? 'tu-app-layout__link tu-app-layout__link--active' : 'tu-app-layout__link'
}

export function AppLayout() {
  const { principal, logout } = useSession()
  const navigate = useNavigate()
  const navLinks = principal?.role === 'customer' ? CUSTOMER_NAV_LINKS : STAFF_NAV_LINKS

  return (
    <div className="tu-app-layout">
      <header className="tu-app-layout__header">
        <nav className="tu-app-layout__nav">
          {navLinks.map((link) => (
            <NavLink key={link.to} to={link.to} className={navLinkClassName}>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="tu-app-layout__account">
          <span className="tu-app-layout__email">{principal?.email}</span>
          <button
            type="button"
            className="tu-app-layout__logout"
            onClick={() => {
              logout().then(() => navigate('/login'))
            }}
          >
            Log out
          </button>
        </div>
      </header>
      <main className="tu-app-layout__main">
        <Outlet />
      </main>
    </div>
  )
}
