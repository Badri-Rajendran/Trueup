import './SignupBrandPanel.css'

// Copy mirrors the real onboarding steps almost verbatim (features/onboarding/components/
// KycStep.jsx, BankLinkStep.jsx) so nothing here surprises a customer once they get there.
const STEPS = [
  {
    title: 'Create your account',
    description: 'Just an email and a password to get started.',
  },
  {
    title: 'Verify your identity',
    description:
      "We use Stripe Identity to confirm who you are — you'll need a government-issued photo ID.",
  },
  {
    title: 'Link your bank',
    description: 'Connect a bank account to fund your investments.',
  },
]

export function SignupBrandPanel() {
  return (
    <div className="tu-signup-panel">
      <div className="tu-signup-panel__content">
        <p className="tu-signup-panel__wordmark">Trueup</p>
        <p className="tu-signup-panel__tagline">
          Invest in one of four model portfolios. We rebalance automatically, every month, so you
          don't have to.
        </p>
        <ol className="tu-signup-panel__steps">
          {STEPS.map((step, index) => (
            <li
              key={step.title}
              className={
                index === 0 ? 'tu-signup-panel__step tu-signup-panel__step--current' : 'tu-signup-panel__step'
              }
            >
              <span className="tu-signup-panel__step-number" aria-hidden="true">
                {index + 1}
              </span>
              <div className="tu-signup-panel__step-body">
                <p className="tu-signup-panel__step-title">{step.title}</p>
                <p className="tu-signup-panel__step-description">{step.description}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="tu-signup-panel__trust">Your data is encrypted in transit and at rest.</p>
      </div>
    </div>
  )
}
