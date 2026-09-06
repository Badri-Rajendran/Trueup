import { Fragment, useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '../components/Button'
import { Icon } from '../components/Icon'
import { useSession } from '../contexts/SessionContext.jsx'
import { useIdentityStatus } from '../features/onboarding/hooks/useIdentityStatus.js'
import { defaultRouteForPrincipal } from '../routes/defaultRoute.js'
import './AppLayout.css'

// Customer nav clustered into 2 logical groups + one standalone item (see AppLayout.css comment
// for why this is spacing/dividers, not a dropdown). Onboarding is deliberately absent here -- it
// only ever appears for a not-yet-approved customer, via ONBOARDING_ONLY_GROUP below.
const CUSTOMER_NAV_GROUPS = [
  {
    key: 'account',
    label: 'Account',
    links: [
      { to: '/dashboard', label: 'Dashboard' },
      { to: '/portfolio', label: 'Portfolio' },
      { to: '/orders', label: 'Orders' },
    ],
  },
  {
    key: 'money',
    label: 'Money',
    links: [
      { to: '/transactions', label: 'Transactions' },
      { to: '/funding', label: 'Funding' },
      { to: '/lots', label: 'Tax lots' },
      { to: '/statements', label: 'Statements' },
      { to: '/fees', label: 'Fees' },
    ],
  },
  {
    key: 'ask',
    label: null,
    links: [{ to: '/chat', label: 'Ask Trueup' }],
  },
]

// A not-yet-approved customer's only reachable route is /onboarding (RequireOnboarded in
// routes/guards.jsx bounces every other link back here) -- so that's the only link the nav shows.
const ONBOARDING_ONLY_GROUP = [
  { key: 'onboarding', label: null, links: [{ to: '/onboarding', label: 'Onboarding' }] },
]

const STAFF_NAV_GROUPS = [
  {
    key: 'staff',
    label: 'Staff console',
    links: [
      { to: '/admin/breaks', label: 'Reconciliation breaks' },
      { to: '/admin/customers', label: 'Customers' },
    ],
  },
]

function navLinkClassName({ isActive }) {
  return isActive ? 'tu-app-layout__link tu-app-layout__link--active' : 'tu-app-layout__link'
}

/**
 * Which nav links are real right now. A customer who hasn't cleared KYC + account approval
 * (ADR 21) can only ever land on /onboarding -- every other customer route bounces them straight
 * back via RequireOnboarded, so showing all 10 links regardless of approval state was the bug:
 * it advertised 9 dead ends to a brand-new customer. While identity status is still loading we
 * show nothing rather than flash a set of links that's about to be wrong either direction.
 */
function useNavGroups(principal) {
  const isCustomer = principal?.role === 'customer'
  const identity = useIdentityStatus(isCustomer ? principal.id : null)

  if (!isCustomer) {
    return { groups: STAFF_NAV_GROUPS, variant: 'staff' }
  }
  if (identity.status === 'idle' || identity.status === 'loading') {
    return { groups: [], variant: 'customer' }
  }
  const isApproved =
    identity.status === 'loaded' &&
    identity.kycStatus === 'approved' &&
    identity.accountApprovalStatus === 'approved'
  return { groups: isApproved ? CUSTOMER_NAV_GROUPS : ONBOARDING_ONLY_GROUP, variant: 'customer' }
}

function initialsFromEmail(email) {
  if (!email) return '?'
  const local = email.split('@')[0]
  const parts = local.split(/[.\-_+]+/).filter(Boolean)
  const source = parts.length >= 2 ? parts[0][0] + parts[1][0] : local.slice(0, 2)
  return source.toUpperCase()
}

function getFocusable(container) {
  if (!container) return []
  return Array.from(
    container.querySelectorAll('a[href], button:not(:disabled), [tabindex]:not([tabindex="-1"])'),
  )
}

/**
 * Shared open/close behaviour for the account dropdown and the mobile nav drawer: Escape closes
 * and returns focus to the trigger, a pointerdown outside the panel closes it, and Tab is trapped
 * inside the panel while it's open. Local to this file -- nothing else needs it yet.
 */
function useDismissablePanel({ active, onClose, panelRef, triggerRef, returnFocusOnEscape = true }) {
  useEffect(() => {
    if (!active) return undefined

    function handlePointerDown(event) {
      const panel = panelRef.current
      const trigger = triggerRef.current
      if (panel?.contains(event.target) || trigger?.contains(event.target)) return
      onClose()
    }

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        if (returnFocusOnEscape) triggerRef.current?.focus()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = getFocusable(panelRef.current)
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [active, onClose, panelRef, triggerRef, returnFocusOnEscape])
}

function AccountMenu({ principal, onLogout, logoutStatus }) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef(null)
  const menuRef = useRef(null)
  const menuId = useId()
  const close = useCallback(() => setOpen(false), [])

  useDismissablePanel({ active: open, onClose: close, panelRef: menuRef, triggerRef })

  useEffect(() => {
    if (open) {
      getFocusable(menuRef.current)[0]?.focus()
    }
  }, [open])

  return (
    <div className="tu-app-layout__account">
      <button
        type="button"
        ref={triggerRef}
        className="tu-app-layout__account-trigger"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={`Account menu, signed in as ${principal?.email ?? ''}`}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="tu-app-layout__avatar" aria-hidden="true">
          {initialsFromEmail(principal?.email)}
        </span>
        <Icon
          name="chevron-down"
          size="sm"
          className={`tu-app-layout__account-chevron${open ? ' tu-app-layout__account-chevron--open' : ''}`}
        />
      </button>
      {open && (
        <div id={menuId} ref={menuRef} className="tu-app-layout__account-menu">
          <p className="tu-app-layout__account-email">{principal?.email}</p>
          <Button
            variant="secondary"
            size="compact"
            loading={logoutStatus === 'pending'}
            onClick={onLogout}
            className="tu-app-layout__account-logout"
          >
            Log out
          </Button>
        </div>
      )}
    </div>
  )
}

function NavDrawer({ groups, variant, open, onClose, triggerRef }) {
  const panelRef = useRef(null)
  const titleId = useId()

  useDismissablePanel({ active: open, onClose, panelRef, triggerRef })

  useEffect(() => {
    if (open) {
      getFocusable(panelRef.current)[0]?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  if (!open) return null

  return (
    <div className="tu-app-layout__drawer-backdrop">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="tu-app-layout__drawer"
      >
        <div className="tu-app-layout__drawer-header">
          <span id={titleId} className="tu-app-layout__drawer-title">
            {variant === 'staff' ? 'Staff console' : 'Menu'}
          </span>
          <button
            type="button"
            className="tu-app-layout__drawer-close"
            onClick={onClose}
            aria-label="Close menu"
          >
            <Icon name="x" />
          </button>
        </div>
        <nav className="tu-app-layout__drawer-nav" aria-label={variant === 'staff' ? 'Staff console' : 'Primary'}>
          {groups.map((group) => (
            <div key={group.key} className="tu-app-layout__drawer-group">
              {group.label && <p className="tu-app-layout__drawer-group-label">{group.label}</p>}
              {group.links.map((link) => (
                <NavLink key={link.to} to={link.to} className={navLinkClassName} onClick={onClose}>
                  {link.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </div>
    </div>
  )
}

export function AppLayout() {
  const { principal, logout } = useSession()
  const navigate = useNavigate()
  const { groups, variant } = useNavGroups(principal)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [logoutStatus, setLogoutStatus] = useState('idle')
  const menuTriggerRef = useRef(null)
  const hasNavItems = groups.some((group) => group.links.length > 0)

  const handleLogout = useCallback(async () => {
    setLogoutStatus('pending')
    try {
      await logout()
    } catch {
      // SessionContext clears principal/session state in a `finally` regardless of API outcome,
      // so the session is already invalid here either way -- just move on to /login.
    } finally {
      navigate('/login')
    }
  }, [logout, navigate])

  return (
    <div className="tu-app-layout">
      <header className="tu-app-layout__header">
        <div className="tu-app-layout__header-inner">
          <Link
            to={defaultRouteForPrincipal(principal)}
            className="tu-app-layout__brand"
            aria-label="Trueup, go to home"
          >
            Trueup
          </Link>

          {hasNavItems && (
            <nav
              className={`tu-app-layout__nav tu-app-layout__nav--${variant}`}
              aria-label={variant === 'staff' ? 'Staff console' : 'Primary'}
            >
              {groups.map((group, index) => (
                <Fragment key={group.key}>
                  {index > 0 && <span className="tu-app-layout__nav-divider" aria-hidden="true" />}
                  <div className="tu-app-layout__nav-group">
                    {/* Group labels show inline only for the staff console -- it's what makes 2
                        links read as a deliberate, named cluster rather than a leftover flat row.
                        Customer groups lean on spacing + dividers alone; "Dashboard/Portfolio/Orders"
                        vs. "Transactions/Funding/..." is self-evidently grouped without a caption. */}
                    {group.label && variant === 'staff' && (
                      <span className="tu-app-layout__nav-group-label">{group.label}</span>
                    )}
                    {group.links.map((link) => (
                      <NavLink key={link.to} to={link.to} className={navLinkClassName}>
                        {link.label}
                      </NavLink>
                    ))}
                  </div>
                </Fragment>
              ))}
            </nav>
          )}

          <div className="tu-app-layout__header-actions">
            {hasNavItems && (
              <button
                type="button"
                ref={menuTriggerRef}
                className="tu-app-layout__menu-trigger"
                aria-haspopup="dialog"
                aria-expanded={drawerOpen}
                aria-label="Open navigation menu"
                onClick={() => setDrawerOpen(true)}
              >
                <Icon name="menu" />
              </button>
            )}
            <AccountMenu principal={principal} onLogout={handleLogout} logoutStatus={logoutStatus} />
          </div>
        </div>
      </header>

      <NavDrawer
        groups={groups}
        variant={variant}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        triggerRef={menuTriggerRef}
      />

      <main className="tu-app-layout__main">
        <Outlet />
      </main>
    </div>
  )
}
