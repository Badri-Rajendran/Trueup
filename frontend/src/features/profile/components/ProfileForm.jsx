import { useEffect, useState } from 'react'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useUpdateProfile } from '../hooks/useUpdateProfile.js'
import './ProfileForm.css'

const FIELDS = [
  { name: 'display_name', label: 'Display name', maxLength: 200 },
  { name: 'phone', label: 'Phone', maxLength: 32, hint: 'E.164 format, e.g. +14155552671' },
  { name: 'mailing_address', label: 'Mailing address', maxLength: 500 },
]

const PHONE_PATTERN = /^\+[1-9]\d{7,14}$/

function valuesFromProfile(profile) {
  return {
    display_name: profile?.display_name ?? '',
    phone: profile?.phone ?? '',
    mailing_address: profile?.mailing_address ?? '',
  }
}

/**
 * `PATCH /profile` is a true partial update (ADR 27): a field the customer never touched must be
 * left out of the request body entirely (the backend reads `model_fields_set`, so "omitted" and
 * "present and null" are both real, distinct states), and a field they cleared to empty must go
 * as an explicit `null`, never `""` -- the backend rejects a whitespace-only string as invalid
 * input rather than treating it as a clear (`_validate_text_field`). `touched` is the only thing
 * that decides what makes it into the PATCH body, not "did the value change from the loaded
 * profile" -- re-typing the same value back out still counts as a deliberate, saved edit.
 */
function buildPatch(values, touched) {
  const patch = {}
  for (const name of Object.keys(touched)) {
    if (!touched[name]) continue
    const trimmed = values[name].trim()
    patch[name] = trimmed === '' ? null : trimmed
  }
  return patch
}

export function ProfileForm({ profile, onSaved }) {
  const { status, error, save } = useUpdateProfile()
  const { showToast } = useToast()
  const [values, setValues] = useState(() => valuesFromProfile(profile))
  const [touched, setTouched] = useState({})
  const [phoneError, setPhoneError] = useState(null)

  // Resyncs whenever `profile` itself changes identity -- the initial load, and again after a
  // successful save hands a fresh object back through `onSaved` -- discarding any now-stale
  // touched/edited state rather than leaving it dangling against a profile that no longer matches.
  useEffect(() => {
    setValues(valuesFromProfile(profile))
    setTouched({})
    setPhoneError(null)
  }, [profile])

  const handleChange = (name) => (event) => {
    setValues((prev) => ({ ...prev, [name]: event.target.value }))
    setTouched((prev) => ({ ...prev, [name]: true }))
    if (name === 'phone') setPhoneError(null)
  }

  const hasChanges = Object.values(touched).some(Boolean)
  const isSubmitting = status === 'submitting'

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!hasChanges) return

    const patch = buildPatch(values, touched)
    if (patch.phone && !PHONE_PATTERN.test(patch.phone)) {
      setPhoneError('Enter a valid phone number in E.164 format, e.g. +14155552671')
      return
    }

    try {
      const updated = await save(patch)
      showToast({ message: 'Profile updated.', tone: 'success' })
      onSaved?.(updated)
    } catch {
      // `status`/`error` below render the failure -- nothing else to do here.
    }
  }

  return (
    <form className="tu-profile-form" onSubmit={handleSubmit}>
      {FIELDS.map((field) => (
        <Input
          key={field.name}
          label={field.label}
          name={field.name}
          value={values[field.name]}
          onChange={handleChange(field.name)}
          maxLength={field.maxLength}
          placeholder="Not set"
          hint={field.name === 'phone' ? field.hint : undefined}
          error={field.name === 'phone' ? phoneError : undefined}
        />
      ))}
      {status === 'error' && (
        <p className="tu-profile-form__error" role="alert">
          {getErrorMessage(error)}
        </p>
      )}
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting || !hasChanges}>
        Save changes
      </Button>
    </form>
  )
}
