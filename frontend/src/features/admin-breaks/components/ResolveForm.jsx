import { useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useResolveBreak } from '../hooks/useResolveBreak.js'
import './ResolveForm.css'

/** Design system §8.6 privileged-action pattern. */
export function ResolveForm({ breakId, onResolved }) {
  const { status, error, resolve } = useResolveBreak()
  const [note, setNote] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [validationMessage, setValidationMessage] = useState(null)

  const isSubmitting = status === 'submitting'

  const handleResolveClick = () => {
    if (!note.trim()) {
      setValidationMessage('Add a resolution note before resolving.')
      return
    }
    setValidationMessage(null)
    setConfirming(true)
  }

  const handleConfirm = () => {
    resolve(breakId, note.trim())
      .then(() => onResolved?.())
      .catch(() => {})
  }

  return (
    <div className="tu-resolve-form">
      <Input
        label="Resolution note"
        name="resolutionNote"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        error={validationMessage}
        disabled={confirming || isSubmitting}
      />
      {!confirming ? (
        <Button variant="danger-outline" onClick={handleResolveClick}>
          Resolve break
        </Button>
      ) : (
        <div className="tu-resolve-form__confirm">
          <p>Mark this break resolved with the note: &ldquo;{note.trim()}&rdquo;?</p>
          {status === 'error' && (
            <p className="tu-resolve-form__error" role="alert">
              {getErrorMessage(error)}
            </p>
          )}
          <div className="tu-resolve-form__actions">
            <Button onClick={handleConfirm} loading={isSubmitting} disabled={isSubmitting}>
              Confirm resolution
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
