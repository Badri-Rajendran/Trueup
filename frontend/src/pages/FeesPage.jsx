import { useCallback, useRef, useState } from 'react'
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
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './FeesPage.css'
import './PageLayout.css'

function FeesPageSkeleton() {
  return (
    <>
      <Card>
        <Skeleton width="140px" height="18px" />
        <Skeleton height="48px" style={{ marginTop: 'var(--space-2)' }} />
        <Skeleton height="18px" style={{ marginTop: 'var(--space-3)' }} />
        <Skeleton height="4px" style={{ marginTop: 'var(--space-3)' }} />
      </Card>
      <div className="tu-fees-page__columns">
        <Card>
          <Skeleton width="120px" height="18px" />
          <Skeleton height="28px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
        <Card>
          <Skeleton height="44px" />
          <Skeleton height="44px" style={{ marginTop: 'var(--space-2)' }} />
          <Skeleton height="44px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
      </div>
    </>
  )
}

export function FeesPage() {
  const { principal } = useSession()
  const { status, accrual, charges, dunning, paymentMethod, error, refetch, setPaymentMethod } = useFees()
  const [billingPeriod] = useState(getBillingPeriod)
  const paymentSectionRef = useRef(null)
  const paymentHeadingRef = useRef(null)

  const focusPaymentMethod = useCallback(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    paymentSectionRef.current?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
    paymentHeadingRef.current?.focus()
  }, [])

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Fees</h1>
        <FeesPageSkeleton />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Fees</h1>
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      </div>
    )
  }

  const isEmpty = hasNoFeeActivity(accrual, charges)

  return (
    <div className="tu-page">
      <div>
        <h1 className="tu-page__title">Fees</h1>
        <p className="tu-fees-page__subtitle">
          A performance fee accrues daily on gains above your high-water mark and is charged monthly.
        </p>
      </div>
      <DunningBanner dunning={dunning} onUpdatePaymentMethod={focusPaymentMethod} />
      {isEmpty ? (
        <EmptyState
          title="No fees yet"
          description="A performance fee only accrues on gains above your account's previous peak. Fee accrual starts after your first valuation day."
        />
      ) : (
        <>
          <AccrualSummary accrual={accrual} billingPeriod={billingPeriod} />
          <div className="tu-fees-page__columns">
            <section>
              <h2 className="tu-page__section-title">High-water mark</h2>
              <HighWaterMarkCard accrual={accrual} />
            </section>
            <section>
              <h2 className="tu-page__section-title">Charge history</h2>
              <ChargeHistory charges={charges} />
            </section>
          </div>
        </>
      )}
      <div id="payment-method" ref={paymentSectionRef} className="tu-fees-page__payment">
        <h2 className="tu-page__section-title" ref={paymentHeadingRef} tabIndex={-1}>
          Payment method
        </h2>
        <Card>
          <PaymentMethodForm customerId={principal.id} currentPaymentMethod={paymentMethod} onAttached={setPaymentMethod} />
        </Card>
      </div>
    </div>
  )
}
