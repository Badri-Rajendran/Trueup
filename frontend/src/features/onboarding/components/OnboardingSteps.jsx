import { Card } from '../../../components/Card'
import { Icon } from '../../../components/Icon'
import './OnboardingSteps.css'

/**
 * The onboarding journey's shell: one Card holding an ordered set of `StepRow`s connected by a
 * rail, so the whole sequence is visible at once instead of hiding every step but the current
 * one. Reuses the same numbered-circle idiom already established on the signup page's brand
 * panel (SignupBrandPanel.jsx) -- this is that same real sequence, continued, not a new device.
 */
export function OnboardingSteps({ children }) {
  return <Card className="tu-onboarding-steps">{children}</Card>
}

/**
 * One step in the sequence. `status` drives both the marker and the row's own emphasis:
 * - `current`   -- the step the customer can act on right now (accent-filled numbered circle).
 * - `locked`    -- not reachable yet (muted outline, no interactive content underneath).
 * - `completed` -- done (a checkmark, never a bare colored dot -- design-system §2.4's own
 *                  never-color-alone rule).
 * `last` suppresses the connector rail below the marker for the final step.
 */
export function StepRow({ number, status, title, last = false, children }) {
  return (
    <div className={`tu-step-row tu-step-row--${status}${last ? ' tu-step-row--last' : ''}`}>
      <div className="tu-step-row__rail">
        <StepMarker number={number} status={status} />
      </div>
      <div className="tu-step-row__body">
        <h2 className="tu-step-row__title">{title}</h2>
        {children}
      </div>
    </div>
  )
}

function StepMarker({ number, status }) {
  if (status === 'completed') {
    return (
      <span className="tu-step-marker tu-step-marker--completed">
        <Icon name="check-circle" size="sm" label="Completed" />
      </span>
    )
  }
  return (
    <span className={`tu-step-marker tu-step-marker--${status}`} aria-hidden="true">
      {number}
    </span>
  )
}
