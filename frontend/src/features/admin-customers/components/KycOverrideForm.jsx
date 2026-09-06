import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Select } from '../../../components/Select'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useKycOverride } from '../hooks/useKycOverride.js'
import './KycOverrideForm.css'

/** Design system §8.6: reopening a locked-`rejected` KYC status is a privileged, audited override. */
export function KycOverrideForm({ customer, onOverridden }) {
  const { status, error, submit } = useKycOverride()
  const [confirming, setConfirming] = useState(false)
  const [decision, setDecision] = useState('approved')
  const isSubmitting = status === 'submitting'

  return (
    <div className="tu-kyc-override">
      {!confirming ? (
        <Button variant="danger-outline" onClick={() => setConfirming(true)}>
          Override KYC status
        </Button>
      ) : (
        <div className="tu-kyc-override__confirm">
          <Select label="New KYC status" value={decision} onChange={(event) => setDecision(event.target.value)}>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </Select>
          <p>
            Set {customer.email}&apos;s KYC status to <strong>{decision}</strong>?
          </p>
          {status === 'error' && (
            <p className="tu-kyc-override__error" role="alert">
              {getErrorMessage(error)}
            </p>
          )}
          <div className="tu-kyc-override__actions">
            <Button
              onClick={() => {
                submit(customer.id, decision)
                  .then(() => {
                    setConfirming(false)
                    onOverridden?.()
                  })
                  .catch(() => {})
              }}
              loading={isSubmitting}
              disabled={isSubmitting}
            >
              Confirm override
            </Button>
            <Button variant="secondary" onClick={() => setConfirming(false)} disabled={isSubmitting}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
