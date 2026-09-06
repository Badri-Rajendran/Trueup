import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { Input } from '../../../components/Input'
import { useToast } from '../../../components/Toast'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useRegister } from '../hooks/useRegister.js'
import './AuthForm.css'

export function RegisterForm() {
  const { status, error, register } = useRegister()
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [validationMessage, setValidationMessage] = useState(null)

  const isSubmitting = status === 'submitting'

  const handleSubmit = async (event) => {
    event.preventDefault()
    setValidationMessage(null)

    if (password !== confirmPassword) {
      setValidationMessage('Passwords do not match.')
      return
    }

    try {
      await register({ email, password })
      showToast({ message: 'Account created — log in to continue.', tone: 'success' })
      navigate('/login')
    } catch {
      // surfaced below via `error`/`status`
    }
  }

  const displayError =
    validationMessage ||
    (status === 'error' ? getErrorMessage(error, 'Registration failed — this email may already be registered.') : null)

  return (
    <form className="tu-auth-form" onSubmit={handleSubmit}>
      <h1 className="tu-auth-form__title">Create your account</h1>
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
        autoComplete="new-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        minLength={8}
        hint="At least 8 characters."
        required
      />
      <Input
        label="Confirm password"
        type="password"
        name="confirmPassword"
        autoComplete="new-password"
        value={confirmPassword}
        onChange={(event) => setConfirmPassword(event.target.value)}
        required
      />
      {displayError && (
        <p className="tu-auth-form__error" role="alert">
          {displayError}
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
