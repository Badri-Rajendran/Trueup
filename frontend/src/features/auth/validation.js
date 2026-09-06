// Pure, framework-free validation rules for the auth forms. No React imports — see
// frontend/CLAUDE.md's layering rule (logic lives outside JSX) and the repo's structure spec,
// which puts a domain's non-presentational logic under its own feature folder.
//
// These functions are individually exported so they are unit-testable as soon as Vitest lands
// (frontend/CLAUDE.md's current MVP policy: no test files this round, but write for it anyway).

// Deliberately looser than the backend's pydantic EmailStr check (backend/app/controllers/api/
// auth.py: RegisterRequest.email / LoginRequest.email) so the client never rejects an address the
// server would accept — the server stays the format authority; this only catches obvious typos
// before a round trip.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function isValidEmail(value) {
  return EMAIL_PATTERN.test(String(value ?? '').trim())
}

/** @returns {string | null} an error message, or null when the email looks well-formed. */
export function validateEmail(value) {
  const trimmed = String(value ?? '').trim()
  if (!trimmed) return 'Email is required.'
  if (!isValidEmail(trimmed)) return 'Enter a valid email address.'
  return null
}

// Backend floor (backend/app/controllers/api/auth.py: RegisterRequest.password =
// Field(min_length=8)) is authoritative and non-negotiable. Everything below it is a
// frontend-only UX improvement layered on top, never a stricter server-side rule reflected back.
export const PASSWORD_MIN_LENGTH = 8
// A password this long clears the strength bar on length alone, without needing a character mix —
// a long passphrase is at least as strong as a short mixed-class password.
export const PASSWORD_STRONG_LENGTH = 12
// "At least 3 of 4 classes" (not all 4): strong enough to rule out `password123`-style entries,
// without forcing every password into a rigid `Aa1!`-shaped template.
export const PASSWORD_CLASS_MINIMUM = 3

function countCharacterClasses(password) {
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/]
  return classes.reduce((count, pattern) => count + (pattern.test(password) ? 1 : 0), 0)
}

/**
 * Live strength breakdown for the register form's checklist. Each flag is independently
 * renderable so the UI can show a met/unmet state per rule as the user types.
 */
export function describePassword(password) {
  const value = String(password ?? '')
  const hasMinLength = value.length >= PASSWORD_MIN_LENGTH
  const classesMet = countCharacterClasses(value)
  const hasStrength = value.length >= PASSWORD_STRONG_LENGTH || classesMet >= PASSWORD_CLASS_MINIMUM
  return {
    hasMinLength,
    classesMet,
    hasStrength,
    isValid: hasMinLength && hasStrength,
  }
}

/** @returns {string | null} an error message, or null when the password clears both bars. */
export function validatePassword(password) {
  const value = String(password ?? '')
  if (!value) return 'Password is required.'
  const { hasMinLength, hasStrength } = describePassword(value)
  if (!hasMinLength) return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`
  if (!hasStrength) {
    return `Use ${PASSWORD_STRONG_LENGTH}+ characters, or mix uppercase, lowercase, numbers, and symbols.`
  }
  return null
}

/** @returns {string | null} an error message, or null once both fields agree. */
export function validatePasswordConfirmation(password, confirmation) {
  if (!confirmation) return 'Confirm your password.'
  if (password !== confirmation) return 'Passwords do not match.'
  return null
}

// pyotp's TOTP default (backend/app/services/identity/auth.py: verify_totp ->
// pyotp.TOTP(secret).verify(code)) is a 6-digit numeric code — not guessed, read from the library
// default the backend actually calls.
export const MFA_CODE_LENGTH = 6
const MFA_CODE_PATTERN = /^\d{6}$/

/** @returns {string | null} an error message, or null when the code is 6 digits. */
export function validateMfaCode(code) {
  const trimmed = String(code ?? '').trim()
  if (!trimmed) return 'Enter your verification code.'
  if (!MFA_CODE_PATTERN.test(trimmed)) return `Enter the ${MFA_CODE_LENGTH}-digit code from your authenticator app.`
  return null
}
