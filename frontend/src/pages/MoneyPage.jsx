import { useCallback, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { AccrualSummary } from '../features/fees/components/AccrualSummary.jsx'
import { ChargeHistory } from '../features/fees/components/ChargeHistory.jsx'
import { DunningBanner } from '../features/fees/components/DunningBanner.jsx'
import { HighWaterMarkCard } from '../features/fees/components/HighWaterMarkCard.jsx'
import { PaymentMethodForm } from '../features/fees/components/PaymentMethodForm.jsx'
import { useFees } from '../features/fees/hooks/useFees.js'
import { getBillingPeriod, hasNoFeeActivity } from '../features/fees/utils/feeSummary.js'
import { BankLinkCard } from '../features/funding/components/BankLinkCard.jsx'
import { CashSummary } from '../features/funding/components/CashSummary.jsx'
import { DepositForm } from '../features/funding/components/DepositForm.jsx'
import { FundingHistoryTable } from '../features/funding/components/FundingHistoryTable.jsx'
import { OutstandingBalanceBanner } from '../features/funding/components/OutstandingBalanceBanner.jsx'
import { WithdrawForm } from '../features/funding/components/WithdrawForm.jsx'
import { useCashSummary } from '../features/funding/hooks/useCashSummary.js'
import { useCurrentBankLink } from '../features/funding/hooks/useCurrentBankLink.js'
import { useFundingHistory } from '../features/funding/hooks/useFundingHistory.js'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './MoneyPage.css'
import './PageLayout.css'

const MODES = [
  { value: 'deposit', label: 'Deposit' },
  { value: 'withdraw', label: 'Withdraw' },
]

/** Toggles between the two directions `FundingHistoryTable`'s one sortable column (Date) can run
 * — stays a small page-local `useState` rather than a dedicated hook. */
function toggleDateSort(prev) {
  if (prev.column !== 'date') return { column: 'date', direction: 'asc' }
  return { column: 'date', direction: prev.direction === 'asc' ? 'desc' : 'asc' }
}

function scrollToAndFocus(sectionRef, headingRef) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  sectionRef.current?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
  headingRef.current?.focus()
}

function CashCard({ cashSummary }) {
  return (
    <Card aria-busy={cashSummary.status === 'loading' || cashSummary.isRefreshing || undefined}>
      {cashSummary.status === 'idle' || cashSummary.status === 'loading' ? (
        <Skeleton height="60px" />
      ) : cashSummary.status === 'error' ? (
        <ErrorState description={getErrorMessage(cashSummary.error)} onRetry={cashSummary.refetch} />
      ) : (
        <CashSummary cashSummary={cashSummary.cashSummary} />
      )}
    </Card>
  )
}

/** Presentational only — `mode`/`onModeChange` are owned by `MoneyPage` so `focusDeposit` (from
 * `OutstandingBalanceBanner`) can force it back to `'deposit'`. */
function ModeToggle({ mode, onModeChange }) {
  return (
    <div className="tu-money-page__mode-toggle" role="group" aria-label="Choose deposit or withdraw">
      {MODES.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`tu-money-page__mode-button${mode === option.value ? ' tu-money-page__mode-button--active' : ''}`}
          aria-pressed={mode === option.value}
          onClick={() => onModeChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function FundingHistorySection({ history }) {
  const [sort, setSort] = useState({ column: 'date', direction: 'desc' })

  const toggleSort = useCallback((column) => {
    if (column !== 'date') return
    setSort(toggleDateSort)
  }, [])

  const sortedEntries = useMemo(() => {
    const dir = sort.direction === 'asc' ? 1 : -1
    return [...history.entries].sort((a, b) => dir * a.effective_date.localeCompare(b.effective_date))
  }, [history.entries, sort])

  return (
    <div>
      <h2 className="tu-page__section-title">Funding history</h2>
      {history.status === 'idle' || history.status === 'loading' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <Skeleton height="44px" />
          <Skeleton height="44px" />
        </div>
      ) : history.status === 'error' && history.entries.length === 0 ? (
        <ErrorState description={getErrorMessage(history.error)} onRetry={history.refetch} />
      ) : (
        <FundingHistoryTable
          entries={sortedEntries}
          sort={sort}
          onSort={toggleSort}
          hasMore={history.nextCursor !== null}
          isLoadingMore={history.status === 'loading-more'}
          loadMoreError={history.status === 'error' ? history.error : null}
          onLoadMore={history.loadMore}
        />
      )}
    </div>
  )
}

function FeesSkeleton() {
  return (
    <>
      <Card>
        <Skeleton width="140px" height="18px" />
        <Skeleton height="48px" style={{ marginTop: 'var(--space-2)' }} />
        <Skeleton height="18px" style={{ marginTop: 'var(--space-3)' }} />
        <Skeleton height="4px" style={{ marginTop: 'var(--space-3)' }} />
      </Card>
      <div className="tu-money-page__fee-columns">
        <Card>
          <Skeleton width="120px" height="18px" />
          <Skeleton height="28px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
        <Card>
          <Skeleton height="44px" />
          <Skeleton height="44px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
      </div>
    </>
  )
}

function FeesSection({ customerId, fees, billingPeriod, paymentSectionRef, paymentHeadingRef }) {
  if (fees.status === 'idle' || fees.status === 'loading') {
    return <FeesSkeleton />
  }

  if (fees.status === 'error') {
    return <ErrorState description={getErrorMessage(fees.error)} onRetry={fees.refetch} />
  }

  const isEmpty = hasNoFeeActivity(fees.accrual, fees.charges)

  return (
    <>
      <DunningBanner dunning={fees.dunning} onUpdatePaymentMethod={() => scrollToAndFocus(paymentSectionRef, paymentHeadingRef)} />
      {isEmpty ? (
        <EmptyState
          title="No fees yet"
          description="A performance fee only accrues on gains above your account's previous peak. Fee accrual starts after your first valuation day."
        />
      ) : (
        <>
          <AccrualSummary accrual={fees.accrual} billingPeriod={billingPeriod} />
          <div className="tu-money-page__fee-columns">
            <section>
              <h2 className="tu-page__section-title">High-water mark</h2>
              <HighWaterMarkCard accrual={fees.accrual} />
            </section>
            <section>
              <h2 className="tu-page__section-title">Charge history</h2>
              <ChargeHistory charges={fees.charges} />
            </section>
          </div>
        </>
      )}
      <div id="payment-method" ref={paymentSectionRef} className="tu-money-page__payment">
        <h2 className="tu-page__section-title" ref={paymentHeadingRef} tabIndex={-1}>
          Payment method
        </h2>
        <Card>
          <PaymentMethodForm customerId={customerId} currentPaymentMethod={fees.paymentMethod} onAttached={fees.setPaymentMethod} />
        </Card>
      </div>
    </>
  )
}

export function MoneyPage() {
  const { principal } = useSession()
  const cashSummary = useCashSummary()
  const history = useFundingHistory()
  const bankLinkState = useCurrentBankLink()
  const fees = useFees()
  const [billingPeriod] = useState(getBillingPeriod)
  const [mode, setMode] = useState('deposit')
  const moveMoneySectionRef = useRef(null)
  const moveMoneyHeadingRef = useRef(null)
  const paymentSectionRef = useRef(null)
  const paymentHeadingRef = useRef(null)

  const handleSubmitted = useCallback(() => {
    cashSummary.refresh()
    history.refetch()
  }, [cashSummary, history])

  // FR-43: pauses the deposit/withdraw flow on a stale bank Item by re-syncing bankLinkState --
  // once it reflects `requires_reauth`, both forms' own `disabledReasonFor` swap to the
  // reconnect-required branch on the next render instead of letting a second submit fail the same
  // way again.
  const handleBankReauthRequired = useCallback(() => {
    bankLinkState.refetch()
  }, [bankLinkState])

  const focusDeposit = useCallback(() => {
    setMode('deposit')
    scrollToAndFocus(moveMoneySectionRef, moveMoneyHeadingRef)
  }, [])

  return (
    <div className="tu-page tu-money-page">
      <div>
        <h1 className="tu-page__title">Money</h1>
        <p className="tu-money-page__subtitle">
          Deposit into or withdraw from your investing account, and manage the performance fee charged on gains.
        </p>
      </div>

      {cashSummary.status === 'loaded' && (
        <OutstandingBalanceBanner cashSummary={cashSummary.cashSummary} onMakeDeposit={focusDeposit} />
      )}

      <CashCard cashSummary={cashSummary} />

      <BankLinkCard
        customerId={principal.id}
        status={bankLinkState.status}
        bankLink={bankLinkState.bankLink}
        error={bankLinkState.error}
        onRetry={bankLinkState.refetch}
        onLinked={bankLinkState.refetch}
      />

      <div ref={moveMoneySectionRef} className="tu-money-page__move-money-section">
        <h2 className="tu-page__section-title" ref={moveMoneyHeadingRef} tabIndex={-1}>
          Move money
        </h2>
        <ModeToggle mode={mode} onModeChange={setMode} />
        <Card>
          {/* Both forms dereference `cashSummary` unconditionally once a bank link exists (caps,
              withdrawable-balance checks) — never mount either before it has actually loaded. */}
          {cashSummary.status === 'idle' || cashSummary.status === 'loading' ? (
            <>
              <Skeleton height="40px" />
              <Skeleton height="18px" style={{ marginTop: 'var(--space-2)' }} />
            </>
          ) : cashSummary.status === 'error' ? (
            <ErrorState description={getErrorMessage(cashSummary.error)} onRetry={cashSummary.refetch} />
          ) : mode === 'deposit' ? (
            <DepositForm
              customerId={principal.id}
              cashSummary={cashSummary.cashSummary}
              bankLink={bankLinkState.bankLink}
              bankLinkLoading={bankLinkState.status !== 'loaded'}
              onSubmitted={handleSubmitted}
              onBankReauthRequired={handleBankReauthRequired}
            />
          ) : (
            <WithdrawForm
              customerId={principal.id}
              cashSummary={cashSummary.cashSummary}
              bankLink={bankLinkState.bankLink}
              bankLinkLoading={bankLinkState.status !== 'loaded'}
              onSubmitted={handleSubmitted}
              onBankReauthRequired={handleBankReauthRequired}
            />
          )}
        </Card>
      </div>

      <FundingHistorySection history={history} />

      <div>
        <h2 className="tu-page__section-title">Performance fee</h2>
        <FeesSection
          customerId={principal.id}
          fees={fees}
          billingPeriod={billingPeriod}
          paymentSectionRef={paymentSectionRef}
          paymentHeadingRef={paymentHeadingRef}
        />
      </div>
    </div>
  )
}
