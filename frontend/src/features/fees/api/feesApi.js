// S10 performance fees — GET /fees, POST /payment-methods.
import { apiClient } from '../../../services/apiClient.js'

// FeeSummaryResponse has no month_to_date_gain or payment_method field; maps only what exists.
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
