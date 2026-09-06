import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useLogin } from '../hooks/useLogin.js'
import './AuthForm.css'

const MFA_STATUSES = new Set(['mfa_required', 'submitting_mfa', 'mfa_error'])
const SUBMITTING_STATUSES = new Set(['submitting', 'submitting_mfa'])

export function LoginForm() {
  const { status, error, login, verifyMfa } = useLogin()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [code, setCode] = useState('')

  const isMfaStep = MFA_STATUSES.has(status)
  const isSubmitting = SUBMITTING_STATUSES.has(status)

  if (isMfaStep) {
    return (
      <form className="tu-auth-form" onSubmit={(event) => {
        event.preventDefault()
        verifyMfa(code)
          .then(() => navigate('/'))
          .catch(() => {})
      }}>
        <h1 className="tu-auth-form__title">Enter your verification code</h1>
        <p className="tu-auth-form__hint">Open your authenticator app and enter the current code.</p>
        <Input
          label="Verification code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
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
      onSubmit={(event) => {
        event.preventDefault()
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
        autoComplete="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        required
      />
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
