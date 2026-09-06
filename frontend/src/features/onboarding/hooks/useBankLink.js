import { useCallback, useEffect, useState } from 'react'
import { usePlaidLink } from 'react-plaid-link'
import { fundingApi } from '../api/fundingApi.js'

// Plaid Link flow: link_token -> Plaid Link modal -> exchange public_token for a bank link.
export function useBankLink(customerId, { onLinked } = {}) {
  const [tokenStatus, setTokenStatus] = useState('loading')
  const [linkToken, setLinkToken] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)

  const fetchLinkToken = useCallback(async () => {
    setTokenStatus('loading')
    try {
      const data = await fundingApi.createLinkToken(customerId)
      setLinkToken(data.link_token)
      setTokenStatus('loaded')
    } catch (err) {
      setError(err)
      setTokenStatus('error')
    }
  }, [customerId])

  useEffect(() => {
    fetchLinkToken()
  }, [fetchLinkToken])

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess: (publicToken) => {
      setStatus('submitting')
      setError(null)
      fundingApi
        .createBankLink(customerId, publicToken)
        .then(() => {
          setStatus('submitted')
          onLinked?.()
        })
        .catch((err) => {
          setError(err)
          setStatus('error')
        })
    },
  })

  return { tokenStatus, status, error, ready, open, retryLinkToken: fetchLinkToken }
}
