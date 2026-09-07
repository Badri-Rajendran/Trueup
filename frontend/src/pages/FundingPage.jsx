import { useCallback, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { BankLinkCard } from '../features/funding/components/BankLinkCard.jsx'
import { CashSummary } from '../features/funding/components/CashSummary.jsx'
import { DepositForm } from '../features/funding/components/DepositForm.jsx'
import { FundingHistoryTable } from '../features/funding/components/FundingHistoryTable.jsx'
import { OutstandingBalanceBanner } from '../features/funding/components/OutstandingBalanceBanner.jsx'
import { WithdrawForm } from '../features/funding/components/WithdrawForm.jsx'
import { useCurrentBankLink } from '../features/funding/hooks/useCurrentBankLink.js'
import { useFunding } from '../features/funding/hooks/useFunding.js'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './FundingPage.css'
import './PageLayout.css'

function FundingPageSkeleton() {
  return (
    <>
      <Card>
        <Skeleton width="280px" height="48px" />
      </Card>
      <Card>
        <Skeleton height="60px" />
      </Card>
      <div className="tu-funding-page__forms">
        <Card>
          <Skeleton height="40px" />
          <Skeleton height="18px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
        <Card>
          <Skeleton height="40px" />
          <Skeleton height="18px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
      </div>
      <Skeleton height="44px" />
      <Skeleton height="44px" />
      <Skeleton height="44px" />
    </>
  )
}

/** Toggles between the two directions a single sortable column (Date) can run — the only sortable
 * column `FundingHistoryTable` has, so this stays a small page-local `useState` rather than a
 * dedicated hook/util (unlike `useLots`' filter+sort, which spans a whole status-filter toolbar). */
function toggleDateSort(prev) {
  if (prev.column !== 'date') return { column: 'date', direction: 'asc' }
  return { column: 'date', direction: prev.direction === 'asc' ? 'desc' : 'asc' }
}

export function FundingPage() {
  const { principal } = useSession()
  const { status, cashSummary, entries, error, refetch, refresh, isRefreshing } = useFunding()
  const bankLinkState = useCurrentBankLink()
  const [sort, setSort] = useState({ column: 'date', direction: 'desc' })
  const depositSectionRef = useRef(null)
  const depositHeadingRef = useRef(null)

  const toggleSort = useCallback((column) => {
    if (column !== 'date') return
    setSort(toggleDateSort)
  }, [])

  const sortedEntries = useMemo(() => {
    const dir = sort.direction === 'asc' ? 1 : -1
    return [...entries].sort((a, b) => dir * a.effective_date.localeCompare(b.effective_date))
  }, [entries, sort])

  const focusDepositForm = useCallback(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    depositSectionRef.current?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
    depositHeadingRef.current?.focus()
  }, [])

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Funding</h1>
        <FundingPageSkeleton />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Funding</h1>
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      </div>
    )
  }

  return (
    <div className="tu-page tu-funding-page">
      <div>
        <h1 className="tu-page__title">Funding</h1>
        <p className="tu-funding-page__subtitle">Deposit into or withdraw from your investing account.</p>
      </div>
      <OutstandingBalanceBanner cashSummary={cashSummary} onMakeDeposit={focusDepositForm} />
      <Card aria-busy={isRefreshing || undefined}>
        <CashSummary cashSummary={cashSummary} />
      </Card>
      <BankLinkCard
        customerId={principal.id}
        status={bankLinkState.status}
        bankLink={bankLinkState.bankLink}
        error={bankLinkState.error}
        onRetry={bankLinkState.refetch}
        onLinked={bankLinkState.refetch}
      />
      <div className="tu-funding-page__forms">
        <div className="tu-funding-page__deposit-section" ref={depositSectionRef}>
          <h2 className="tu-page__section-title" ref={depositHeadingRef} tabIndex={-1}>
            Deposit
          </h2>
          <Card>
            <DepositForm
              customerId={principal.id}
              cashSummary={cashSummary}
              bankLink={bankLinkState.bankLink}
              bankLinkLoading={bankLinkState.status !== 'loaded'}
              onSubmitted={refresh}
            />
          </Card>
        </div>
        <div>
          <h2 className="tu-page__section-title">Withdraw</h2>
          <Card>
            <WithdrawForm
              customerId={principal.id}
              cashSummary={cashSummary}
              bankLink={bankLinkState.bankLink}
              bankLinkLoading={bankLinkState.status !== 'loaded'}
              onSubmitted={refresh}
            />
          </Card>
        </div>
      </div>
      <div>
        <h2 className="tu-page__section-title">Funding history</h2>
        <FundingHistoryTable entries={sortedEntries} sort={sort} onSort={toggleSort} />
      </div>
    </div>
  )
}
