import { useCallback, useEffect, useState } from 'react'
import { identityApi } from '../api/identityApi.js'

const IDLE = { status: 'idle', kycStatus: null, accountApprovalStatus: null, error: null }

// GET /identity/status/<customer_id>; pass null for non-customer principals.
export function useIdentityStatus(customerId) {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    if (!customerId) {
      setState(IDLE)
      return
    }
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const data = await identityApi.getStatus(customerId)
      setState({
        status: 'loaded',
        kycStatus: data.kyc_status,
        accountApprovalStatus: data.account_approval_status,
        error: null,
      })
    } catch (error) {
      setState({ status: 'error', kycStatus: null, accountApprovalStatus: null, error })
    }
  }, [customerId])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
