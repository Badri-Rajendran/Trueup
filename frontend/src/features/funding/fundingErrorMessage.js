import { getErrorMessage } from '../../utils/apiErrorMessage.js'

// deposit/withdrawal_service.py error codes
const SPECIFIC_MESSAGES = {
  no_active_bank_link: 'Link a bank account before you can do this.',
  bank_reauth_required: 'Your linked bank needs to be reconnected before you can do this.',
  insufficient_withdrawable_cash: "That's more than your withdrawable cash.",
  deposit_cap_exceeded_per_transaction: 'That deposit is above the per-transaction limit.',
  deposit_cap_exceeded_per_day: "That would put you over today's deposit limit.",
}

export function getFundingErrorMessage(error) {
  if (!error) return null
  if (SPECIFIC_MESSAGES[error.code]) return SPECIFIC_MESSAGES[error.code]
  if (error.code?.startsWith('kyc_status_') || error.code?.startsWith('account_approval_status_')) {
    return 'Your account is not yet fully approved for funding.'
  }
  return getErrorMessage(error)
}
