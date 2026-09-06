// S10 performance fees — GET /fees, POST /payment-methods.
import { apiClient } from '../../../services/apiClient.js'

// The real `FeeSummaryResponse` has no `month_to_date_gain` field (that would need a valuation
// dollar-gain figure this endpoint doesn't compute) and no `payment_method` field (there is no GET
// that returns the currently-attached method) — both were mock inventions. This maps only what the
// backend actually returns rather than inventing either.
function toAccrual(data) {
  return {
    peak_value: data.high_water_mark?.peak_value ?? null,
    updated_at: data.high_water_mark?.updated_at ?? null,
    accrual_to_date: data.accrual_to_date,
  }
}

export const feesApi = {
  get: async () => {
    const data = await apiClient.get('/fees')
    return { accrual: toAccrual(data), charges: data.charges, dunning: data.dunning }
  },
  getForCustomer: async (customerId) => {
    const data = await apiClient.get(`/fees?customer_id=${customerId}`)
    return { accrual: toAccrual(data), charges: data.charges, dunning: data.dunning }
  },
  attachPaymentMethod: async (customerId, paymentMethodId) => {
    const data = await apiClient.post('/payment-methods', {
      customer_id: customerId,
      payment_method_id: paymentMethodId,
    })
    return data
  },
}
