import { describe, expect, it } from 'vitest'
import { formatMoney } from './format.js'

describe('formatMoney', () => {
  it('masks a positive value with thousands separators and 2 decimals', () => {
    expect(formatMoney('12480.06')).toBe('$12,480.06')
  })

  it('masks a negative value with a leading minus outside the dollar sign', () => {
    expect(formatMoney('-1234.5')).toBe('-$1,234.50')
  })
})
