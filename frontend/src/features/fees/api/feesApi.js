// MOCK — no backend endpoint exists yet (S10 performance fees). Replace with a real fetch call
// once that spec ships. Field names match `docs/specs/10-performance-fees.md`'s
// `high_water_mark`/`fee_accrual`/`fee_charge`/`dunning_state` tables.
import { mockClient } from '../../../services/mockClient.js'

const NAMESPACE = 'fees'

function seed() {
  return {
    accrual: {
      peak_value: '52000.00',
      month_to_date_gain: '1200.00',
      month_to_date_fee: '240.00',
    },
    charges: [
      {
        id: 'charge-1',
        billing_period_start: '2026-07-01',
        billing_period_end: '2026-07-31',
        total_accrued: '210.00',
        status: 'succeeded',
      },
      {
        id: 'charge-2',
        billing_period_start: '2026-08-01',
        billing_period_end: '2026-08-31',
        total_accrued: '240.00',
        status: 'dunning',
      },
    ],
    dunning: {
      status: 'retrying',
      attempt_number: 2,
      max_attempts: 4,
      next_retry_at: '2026-09-10T00:00:00Z',
    },
    payment_method: null,
  }
}

export const feesApi = {
  get: () => {
    const store = mockClient.getStore(NAMESPACE, seed)
    return mockClient.request({
      accrual: store.accrual,
      charges: store.charges,
      dunning: store.dunning,
      payment_method: store.payment_method,
    })
  },
  attachPaymentMethod: (paymentMethod) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    store.payment_method = paymentMethod
    return mockClient.request(store.payment_method)
  },
}
