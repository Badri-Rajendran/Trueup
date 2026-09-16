import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useKycOverride } from '../hooks/useKycOverride.js'
import './KycOverrideForm.css'

/** Design system §8.6 privileged-action pattern. The backend action (`POST
 * /admin/kyc-overrides/<id>`) unconditionally reopens a locked `rejected` KYC status to `pending`
 * with an audit `reason` -- there is no approve/reject decision to make here, so this only renders
 * for a customer currently locked out (S8 §4 row 5, S8 §6 edge case 3). */
export function KycOverrideForm({ customer, onOverridden }) {
  const { status, error, submit } = useKycOverride()
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')
  const isSubmitting = status === 'submitting'

  if (customer.kyc_status !== 'rejected') {
    return null
  }

  return (
    <div className="tu-kyc-override">
      {!confirming ? (
        <Button variant="danger-outline" onClick={() => setConfirming(true)}>
          Reopen KYC for resubmission
        </Button>
      ) : (
        <div className="tu-kyc-override__confirm">
          <p>
            Reopen {customer.email}&apos;s KYC status to <strong>pending</strong> so they can resubmit?
          </p>
          <Input
            label="Reason"
            name="reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why is this override being made?"
          />
          {status === 'error' && (
            <p className="tu-kyc-override__error" role="alert">
              {getErrorMessage(error)}
            </p>
          )}
          <div className="tu-kyc-override__actions">
            <Button
              onClick={() => {
                submit(customer.id, reason.trim())
                  .then(() => {
                    setConfirming(false)
                    setReason('')
                    onOverridden?.()
                  })
                  .catch(() => {})
              }}
              loading={isSubmitting}
              disabled={isSubmitting || !reason.trim()}
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
