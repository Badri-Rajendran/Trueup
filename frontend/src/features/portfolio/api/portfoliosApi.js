// MOCK — no backend endpoint exists yet (S9 rebalancing / model portfolios). Replace with a real
// fetch call once that spec ships. Function signatures match what `GET /portfolios/models` and
// `GET/POST /portfolios/assignment` would return.
import { mockClient } from '../../../services/mockClient.js'

const NAMESPACE = 'portfolio'

function seed() {
  return {
    models: [
      {
        id: 'model-conservative',
        name: 'Conservative',
        description: 'Capital preservation first — a bond-heavy allocation with a small equity sleeve.',
        target_weights: [
          { security_id: 'sec-bnd', symbol: 'BND', target_weight: '0.6000' },
          { security_id: 'sec-vti', symbol: 'VTI', target_weight: '0.3000' },
          { security_id: 'sec-cash', symbol: 'CASH', target_weight: '0.1000' },
        ],
      },
      {
        id: 'model-balanced',
        name: 'Balanced',
        description: 'An even split between growth and stability.',
        target_weights: [
          { security_id: 'sec-vti', symbol: 'VTI', target_weight: '0.4500' },
          { security_id: 'sec-vxus', symbol: 'VXUS', target_weight: '0.1500' },
          { security_id: 'sec-bnd', symbol: 'BND', target_weight: '0.3500' },
          { security_id: 'sec-cash', symbol: 'CASH', target_weight: '0.0500' },
        ],
      },
      {
        id: 'model-growth',
        name: 'Growth',
        description: 'Mostly equities, a modest bond allocation to dampen volatility.',
        target_weights: [
          { security_id: 'sec-vti', symbol: 'VTI', target_weight: '0.6000' },
          { security_id: 'sec-vxus', symbol: 'VXUS', target_weight: '0.2500' },
          { security_id: 'sec-bnd', symbol: 'BND', target_weight: '0.1500' },
        ],
      },
      {
        id: 'model-aggressive',
        name: 'Aggressive',
        description: 'Maximum equity exposure for a long time horizon.',
        target_weights: [
          { security_id: 'sec-vti', symbol: 'VTI', target_weight: '0.7000' },
          { security_id: 'sec-vxus', symbol: 'VXUS', target_weight: '0.3000' },
        ],
      },
    ],
    // The orderable universe (S9's model composition, minus CASH — not a security you place an
    // order for). `reference_price` stands in for a market-data quote (no quote endpoint is
    // exposed to the frontend either), needed for OrderForm's notional preview and `POST /orders`.
    securities: [
      { security_id: 'sec-vti', symbol: 'VTI', reference_price: '265.40' },
      { security_id: 'sec-vxus', symbol: 'VXUS', reference_price: '58.20' },
      { security_id: 'sec-bnd', symbol: 'BND', reference_price: '72.85' },
    ],
    assignment: null,
  }
}

export const portfoliosApi = {
  getModels: () => mockClient.request(mockClient.getStore(NAMESPACE, seed).models),
  getSecurities: () => mockClient.request(mockClient.getStore(NAMESPACE, seed).securities),
  getAssignment: () => mockClient.request(mockClient.getStore(NAMESPACE, seed).assignment),
  assign: (modelId) => {
    const store = mockClient.getStore(NAMESPACE, seed)
    const model = store.models.find((candidate) => candidate.id === modelId)
    store.assignment = { model_id: modelId, model_name: model?.name, assigned_at: new Date().toISOString() }
    return mockClient.request(store.assignment)
  },
}
