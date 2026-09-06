// MOCK — no backend endpoint exists yet (admin customer directory/detail/KYC-override). Replace
// with a real fetch call once that spec ships.
import { mockClient } from '../../../services/mockClient.js'

const NAMESPACE = 'admin-customers'

function seed() {
  return {
    customers: [
      {
        id: 'cust-1',
        email: 'amelia.chen@example.com',
        kyc_status: 'approved',
        account_approval_status: 'approved',
        has_open_break: false,
      },
      {
        id: 'cust-2',
        email: 'marcus.webb@example.com',
        kyc_status: 'pending',
        account_approval_status: 'pending',
        has_open_break: false,
      },
      {
        id: 'cust-3',
        email: 'priya.natarajan@example.com',
        kyc_status: 'rejected',
        account_approval_status: 'rejected',
        has_open_break: true,
      },
      {
        id: 'cust-4',
        email: 'daniel.osei@example.com',
        kyc_status: 'approved',
        account_approval_status: 'approved',
        has_open_break: true,
      },
    ],
  }
}

export const adminCustomersApi = {
  search: (query) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    const results = query ? store.customers.filter((c) => c.email.toLowerCase().includes(query.toLowerCase())) : []
    return mockClient.request(results)
  },
  getDetail: (customerId) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    return mockClient.request(store.customers.find((c) => c.id === customerId) || null)
  },
  submitKycOverride: (customerId, decision) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    const customer = store.customers.find((c) => c.id === customerId)
    if (customer) {
      customer.kyc_status = decision
      if (decision === 'approved') {
        customer.account_approval_status = 'approved'
      }
    }
    return mockClient.request(customer)
  },
  getFees: () =>
    mockClient.request({
      accrual: { peak_value: '31000.00', month_to_date_gain: '400.00', month_to_date_fee: '80.00' },
      dunning: null,
    }),
}
