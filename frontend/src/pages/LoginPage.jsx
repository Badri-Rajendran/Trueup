import { LoginForm } from '../features/auth/components/LoginForm.jsx'
import { AuthLayout } from './AuthLayout.jsx'

export function LoginPage() {
  return (
    <AuthLayout>
      <LoginForm />
    </AuthLayout>
  )
}
