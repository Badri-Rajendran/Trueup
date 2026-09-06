import { useCallback, useEffect, useState } from 'react'
import { portfoliosApi } from '../api/portfoliosApi.js'

const IDLE = { status: 'idle', securities: [], error: null }

/** The orderable universe — consumed cross-feature by `orders`' OrderForm (mock-data owner stays
 * `portfolio`). There is no dedicated securities/quote endpoint, so this derives the list from
 * `GET /portfolios/models`'s `target_weights`, deduped by `security_id` — a customer enters the
 * reference price themselves (no quote source exists to invent one from). */
export function useSecurities() {
  const [state, setState] = useState(IDLE)

  const refetch = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }))
    try {
      const models = await portfoliosApi.getModels()
      const bySecurityId = new Map()
      for (const model of models) {
        for (const weight of model.target_weights) {
          if (!bySecurityId.has(weight.security_id)) {
            bySecurityId.set(weight.security_id, {
              security_id: weight.security_id,
              symbol: weight.symbol,
            })
          }
        }
      }
      setState({ status: 'loaded', securities: [...bySecurityId.values()], error: null })
    } catch (error) {
      setState({ status: 'error', securities: [], error })
    }
  }, [])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { ...state, refetch }
}
