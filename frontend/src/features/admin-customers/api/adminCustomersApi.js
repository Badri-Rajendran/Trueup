// MOCK -- the real backend routes (GET /admin/customers*, POST /admin/kyc-overrides/<id>) exist
// and are tested (backend/app/controllers/admin/), the frontend just hasn't been wired to them
// yet. See docs/superpowers/specs/2026-09-05-frontend-completion-design.md.
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
}
