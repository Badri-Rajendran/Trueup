// Maps an ApiError's stable `code` (never field-level detail) to customer-facing copy.
const MESSAGES_BY_CODE = {
  unauthenticated: 'Incorrect email or password.',
  validation_failed: 'Check your details and try again.',
  email_taken: 'An account with this email already exists.',
  forbidden: "You don't have access to do that.",
  not_found: 'Not found.',
  conflict: 'That request has already been submitted.',
  too_many_requests: 'Too many attempts — please wait a moment and try again.',
  network_error: 'Network error — check your connection and try again.',
}

export function getErrorMessage(error, fallback = 'Something went wrong. Please try again.') {
  return MESSAGES_BY_CODE[error?.code] || fallback
}
