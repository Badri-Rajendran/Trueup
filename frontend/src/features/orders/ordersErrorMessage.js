import { getErrorMessage } from '../../utils/apiErrorMessage.js'

// order_service.py / orders.py error codes -- every real rejection reason a POST /orders or
// POST /orders/<id>/approve can return, so a real cause is never swallowed into the generic
// fallback (which is what "some error occurred" looked like before this map existed).
const SPECIFIC_MESSAGES = {
  customer_not_eligible: "Your account isn't eligible to place orders yet.",
  kyc_verification_pending: 'Your identity verification is still pending — you can place orders once it completes.',
  kyc_verification_rejected: 'Your identity verification was not approved. Contact support to resolve this.',
  account_approval_pending: 'Your account is still pending approval — you can place orders once it completes.',
  account_approval_rejected: 'Your account was not approved. Contact support to resolve this.',
  insufficient_investable_cash: "You don't have enough investable cash for this order.",
}

export function getOrdersErrorMessage(error) {
  if (!error) return null
  if (SPECIFIC_MESSAGES[error.code]) return SPECIFIC_MESSAGES[error.code]
  return getErrorMessage(error)
}
