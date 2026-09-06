// MOCK — no backend endpoint exists yet (S5 has the ledger data, no controller). Replace with a
// real fetch call once that spec ships. Field names match `docs/specs/5-tax-lots-and-corporate-
// actions.md`'s `tax_lot`/`lot_consumption` tables.
import { mockClient } from '../../../services/mockClient.js'

const NAMESPACE = 'lots'

function seed() {
  return {
    lots: [
      {
        id: 'lot-1',
        security_id: 'sec-vti',
        symbol: 'VTI',
        quantity_opened: '10.000000',
        quantity_remaining: '10.000000',
        original_cost_basis: '2400.00',
        adjusted_basis: '2400.00',
        acquired_at: '2026-06-15',
        is_provisional: false,
      },
      {
        id: 'lot-2',
        security_id: 'sec-bnd',
        symbol: 'BND',
        quantity_opened: '15.000000',
        quantity_remaining: '15.000000',
        original_cost_basis: '1080.00',
        adjusted_basis: '1150.00',
        acquired_at: '2026-07-02',
        is_provisional: true,
        wash_sale_note: 'A prior loss sale on BND was disallowed and added to this lot’s basis (ADR 11).',
      },
      {
        id: 'lot-3',
        security_id: 'sec-vxus',
        symbol: 'VXUS',
        quantity_opened: '8.000000',
        quantity_remaining: '8.000000',
        original_cost_basis: '448.00',
        adjusted_basis: '448.00',
        acquired_at: '2026-08-11',
        is_provisional: false,
      },
    ],
  }
}

export const lotsApi = {
  list: () => mockClient.request(mockClient.getStore(NAMESPACE, seed).lots),
}
