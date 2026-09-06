import { useCallback, useEffect, useState } from 'react'
import { usePlaidLink } from 'react-plaid-link'
import { fundingApi } from '../api/fundingApi.js'

/**
 * The full Plaid Link flow: mint a `link_token` (`POST /funding/link-token`), open Plaid Link with
 * it, then exchange the resulting `public_token` for a linked bank account
 * (`POST /funding/bank-links`). `tokenStatus` covers fetching the link token (a mount-time sync,
 * hence its own `useEffect`); `status` covers the exchange, triggered by Plaid Link's own
 * `onSuccess` callback rather than a form submit.
 */
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
