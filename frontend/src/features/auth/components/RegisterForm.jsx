import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useRegister } from '../hooks/useRegister.js'
import {
  describePassword,
  validateEmail,
  validatePassword,
  validatePasswordConfirmation,
} from '../validation.js'
import './AuthForm.css'

const EMAIL_ID = 'register-email'
const PASSWORD_ID = 'register-password'
const PASSWORD_RULES_ID = 'register-password-rules'
const CONFIRM_PASSWORD_ID = 'register-confirm-password'

const FIELD_VALIDATORS = {
  email: (values) => validateEmail(values.email),
  password: (values) => validatePassword(values.password),
  confirmPassword: (values) => validatePasswordConfirmation(values.password, values.confirmPassword),
}

const FIELD_FOCUS_IDS = {
  email: EMAIL_ID,
  password: PASSWORD_ID,
  confirmPassword: CONFIRM_PASSWORD_ID,
}

export function RegisterForm() {
  const { status, error, register } = useRegister()
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [touched, setTouched] = useState({})
  const [fieldErrors, setFieldErrors] = useState({})

  const isSubmitting = status === 'submitting'
  const values = { email, password, confirmPassword }
  const strength = describePassword(password)
  // Input's own aria-describedby (wired to its inline error message, id `${id}-message`) would be
  // clobbered by ours below since {...rest} is spread after it — so reconstruct both ids here
  // rather than losing the error announcement while the strength checklist is attached.
  const passwordDescribedBy = [PASSWORD_RULES_ID, fieldErrors.password ? `${PASSWORD_ID}-message` : null]
    .filter(Boolean)
    .join(' ')

  const runValidator = (field, nextValues) => FIELD_VALIDATORS[field](nextValues)

  const validateField = (field, nextValues = values) => {
    const message = runValidator(field, nextValues)
    setFieldErrors((prev) => ({ ...prev, [field]: message }))
    return message
  }

  const handleBlur = (field) => () => {
    setTouched((prev) => ({ ...prev, [field]: true }))
    validateField(field)
  }

  const handleChange = (field, setter) => (event) => {
    const nextValue = event.target.value
    setter(nextValue)
    const nextValues = { ...values, [field]: nextValue }
    // Re-validate live once a field has already been touched, so a fixed error clears
    // immediately instead of waiting for the next blur; confirm-password also re-checks live
    // once the password itself changes, since a match can break without confirm being edited.
    if (touched[field]) validateField(field, nextValues)
    if (field === 'password' && touched.confirmPassword) validateField('confirmPassword', nextValues)
    if (field === 'confirmPassword' && nextValue.length > 0 && password.length > 0) {
      validateField('confirmPassword', nextValues)
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()

    const fields = ['email', 'password', 'confirmPassword']
    const errors = Object.fromEntries(fields.map((field) => [field, runValidator(field, values)]))
    setFieldErrors(errors)
    setTouched({ email: true, password: true, confirmPassword: true })

    const firstInvalid = fields.find((field) => errors[field])
    if (firstInvalid) {
      document.getElementById(FIELD_FOCUS_IDS[firstInvalid])?.focus()
      return
    }

    try {
      await register({ email, password })
      showToast({ message: 'Account created — log in to continue.', tone: 'success' })
      navigate('/login')
    } catch {
      // surfaced below via `error`/`status`; input state is left untouched so the user can retry
    }
  }

  const serverErrorMessage =
    status === 'error' ? getErrorMessage(error, 'Registration failed — this email may already be registered.') : null

  return (
    <form className="tu-auth-form" onSubmit={handleSubmit} noValidate>
      <h1 className="tu-auth-form__title">Create your account</h1>
      <Input
        label="Email"
        type="email"
        name="email"
        id={EMAIL_ID}
        autoComplete="email"
        value={email}
        onChange={handleChange('email', setEmail)}
        onBlur={handleBlur('email')}
        error={fieldErrors.email}
        required
      />
      <div>
        <Input
          label="Password"
          type="password"
          name="password"
          id={PASSWORD_ID}
          autoComplete="new-password"
          value={password}
          onChange={handleChange('password', setPassword)}
          onBlur={handleBlur('password')}
          error={fieldErrors.password}
          aria-describedby={passwordDescribedBy}
          required
        />
        <ul className="tu-password-rules" id={PASSWORD_RULES_ID}>
          <li className={`tu-password-rules__item${strength.hasMinLength ? ' tu-password-rules__item--met' : ''}`}>
            <RuleIcon met={strength.hasMinLength} />
            At least 8 characters
            <span className="tu-visually-hidden">{strength.hasMinLength ? ' — met' : ' — not met'}</span>
          </li>
          <li className={`tu-password-rules__item${strength.hasStrength ? ' tu-password-rules__item--met' : ''}`}>
            <RuleIcon met={strength.hasStrength} />
            12+ characters, or a mix of 3+ of: lowercase, uppercase, number, symbol
            <span className="tu-visually-hidden">{strength.hasStrength ? ' — met' : ' — not met'}</span>
          </li>
        </ul>
      </div>
      <Input
        label="Confirm password"
        type="password"
        name="confirmPassword"
        id={CONFIRM_PASSWORD_ID}
        autoComplete="new-password"
        value={confirmPassword}
        onChange={handleChange('confirmPassword', setConfirmPassword)}
        onBlur={handleBlur('confirmPassword')}
        error={fieldErrors.confirmPassword}
        required
      />
      {serverErrorMessage && (
        <p className="tu-auth-form__error" role="alert">
          {serverErrorMessage}
        </p>
      )}
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Create account
      </Button>
      <p className="tu-auth-form__footer">
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </form>
  )
}

function RuleIcon({ met }) {
  return (
    <svg className="tu-password-rules__icon" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      {met ? (
        <path
          d="M2.5 6.25 5 8.75 9.5 3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <circle cx="6" cy="6" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.2" />
      )}
    </svg>
  )
}
