import { RegisterForm } from '../features/auth/components/RegisterForm.jsx'
import { SignupBrandPanel } from '../features/auth/components/SignupBrandPanel.jsx'
import { AuthLayout } from './AuthLayout.jsx'

export function RegisterPage() {
  return (
    <AuthLayout variant="split" panel={<SignupBrandPanel />}>
      <RegisterForm />
    </AuthLayout>
  )
}
