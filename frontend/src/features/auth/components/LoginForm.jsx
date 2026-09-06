import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useLogin } from '../hooks/useLogin.js'
import { validateEmail, validateMfaCode } from '../validation.js'
import './AuthForm.css'

const MFA_STATUSES = new Set(['mfa_required', 'submitting_mfa', 'mfa_error'])
const ENROLL_STATUSES = new Set(['mfa_enroll_required', 'enrolling', 'mfa_enroll_error'])
const SUBMITTING_STATUSES = new Set(['submitting', 'submitting_mfa', 'enrolling'])

const EMAIL_ID = 'login-email'
const CODE_ID = 'login-mfa-code'

export function LoginForm() {
  const { status, error, enrollment, login, enrollMfa, verifyMfa } = useLogin()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [code, setCode] = useState('')
  const [emailTouched, setEmailTouched] = useState(false)
  const [emailError, setEmailError] = useState(null)
  const [codeError, setCodeError] = useState(null)

  const isMfaStep = MFA_STATUSES.has(status)
  const isEnrollStep = ENROLL_STATUSES.has(status)
  const isSubmitting = SUBMITTING_STATUSES.has(status)

  const handleEmailBlur = () => {
    setEmailTouched(true)
    setEmailError(validateEmail(email))
  }

  const handleEmailChange = (event) => {
    const nextValue = event.target.value
    setEmail(nextValue)
    if (emailTouched) setEmailError(validateEmail(nextValue))
  }

  if (isEnrollStep) {
    return (
      <form
        className="tu-auth-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          enrollMfa().catch(() => {})
        }}
      >
        <h1 className="tu-auth-form__title">Set up two-factor authentication</h1>
        <p className="tu-auth-form__hint">
          Staff accounts require an authenticator app. Set yours up now — you&apos;ll enter a code
          from it every time you log in.
        </p>
        {status === 'mfa_enroll_error' && (
          <p className="tu-auth-form__error" role="alert">
            {getErrorMessage(error, 'Could not start setup. Please try again.')}
          </p>
        )}
        <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
          Set up authenticator
        </Button>
      </form>
    )
  }

  if (isMfaStep) {
    return (
      <form
        className="tu-auth-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          const message = validateMfaCode(code)
          setCodeError(message)
          if (message) {
            document.getElementById(CODE_ID)?.focus()
            return
          }
          verifyMfa(code)
            .then(() => navigate('/'))
            .catch(() => {})
        }}
      >
        <h1 className="tu-auth-form__title">Enter your verification code</h1>
        {enrollment ? (
          <>
            <p className="tu-auth-form__hint">
              Add this key to your authenticator app, then enter the code it shows. This key is
              displayed once — it will not be shown again after you finish logging in.
            </p>
            {/* The secret itself, not a QR image: rendering one would mean adding a QR dependency
                for a single screen, and every authenticator app accepts manual key entry. */}
            <p className="tu-auth-form__secret">
              <code>{enrollment.secret}</code>
            </p>
          </>
        ) : (
          <p className="tu-auth-form__hint">
            Open your authenticator app and enter the current code.
          </p>
        )}
        <Input
          label="Verification code"
          name="code"
          id={CODE_ID}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => {
            const nextValue = event.target.value
            setCode(nextValue)
            if (codeError) setCodeError(validateMfaCode(nextValue))
          }}
          onBlur={() => setCodeError(validateMfaCode(code))}
          error={codeError}
          required
        />
        {status === 'mfa_error' && (
          <p className="tu-auth-form__error" role="alert">
            {getErrorMessage(error, 'Invalid code. Please try again.')}
          </p>
        )}
        <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
          Verify
        </Button>
      </form>
    )
  }

  return (
    <form
      className="tu-auth-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        const message = validateEmail(email)
        setEmailError(message)
        setEmailTouched(true)
        if (message) {
          document.getElementById(EMAIL_ID)?.focus()
          return
        }
        login({ email, password, remember })
          .then((result) => {
            if (!result.mfaRequired) navigate('/')
          })
          .catch(() => {})
      }}
    >
      <h1 className="tu-auth-form__title">Log in</h1>
      <Input
        label="Email"
        type="email"
        name="email"
        id={EMAIL_ID}
        autoComplete="email"
        value={email}
        onChange={handleEmailChange}
        onBlur={handleEmailBlur}
        error={emailError}
        required
      />
      {/* Presence-only, deliberately: a login form must never reject a real, older,
          already-provisioned password because a newer strength policy exists. Do not add a
          strength/format rule here — that belongs on signup only (see validation.js). */}
      <Input
        label="Password"
        type="password"
        name="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        required
      />
      <label className="tu-auth-form__checkbox">
        <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
        Remember me
      </label>
      {status === 'error' && (
        <p className="tu-auth-form__error" role="alert">
          {getErrorMessage(error)}
        </p>
      )}
      <Button type="submit" loading={isSubmitting} disabled={isSubmitting}>
        Log in
      </Button>
      <p className="tu-auth-form__footer">
        Don&apos;t have an account? <Link to="/register">Register</Link>
      </p>
    </form>
  )
}
