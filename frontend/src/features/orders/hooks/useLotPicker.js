import Decimal from 'decimal.js'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLots } from '../../lots/hooks/useLots.js'

/**
 * Specific-ID tax-lot designation for a sell order (FR-20/ADR-4) -- a client-side UX nicety that
 * mirrors Task 3's placement-time validation so the customer sees the shortfall before submitting;
 * the server-side check in `LotDesignationService` remains the actual authority, this is not a
 * substitute for it. Sourced from `useLots()` (Task 5), filtered to `securityId`'s own lots with
 * `quantity_remaining > 0` -- a lot with nothing left to sell is never a valid designation target.
 *
 * An empty selection is a valid, first-class state (it means FIFO, ADR-4's default), never a
 * forced choice -- `isShort` only trips once the customer has actually started picking lots.
 */
export function useLotPicker({ securityId, requestedQuantity }) {
  const lots = useLots()
  const [selectedLotIds, setSelectedLotIds] = useState([])

  // A different security invalidates any prior selection -- those lot ids belong to another
  // security entirely and would fail Task 3's own `unknown_tax_lot` check if resubmitted.
  useEffect(() => {
    setSelectedLotIds([])
  }, [securityId])

  const candidates = useMemo(
    () =>
      lots.lots.filter(
        (lot) => lot.security_id === securityId && new Decimal(lot.quantity_remaining).greaterThan(0),
      ),
    [lots.lots, securityId],
  )

  const toggleLot = useCallback((lotId) => {
    setSelectedLotIds((prev) => (prev.includes(lotId) ? prev.filter((id) => id !== lotId) : [...prev, lotId]))
  }, [])

  const clearSelection = useCallback(() => setSelectedLotIds([]), [])

  const selectedTotal = useMemo(
    () =>
      candidates
        .filter((lot) => selectedLotIds.includes(lot.id))
        .reduce((sum, lot) => sum.plus(lot.quantity_remaining), new Decimal(0)),
    [candidates, selectedLotIds],
  )

  const requested = useMemo(() => {
    if (!requestedQuantity) return null
    try {
      const decimal = new Decimal(requestedQuantity)
      return decimal.isFinite() && decimal.greaterThan(0) ? decimal : null
    } catch {
      return null
    }
  }, [requestedQuantity])

  // Only a non-empty selection can be "short" -- an empty one is FIFO, not a shortfall.
  const isShort = selectedLotIds.length > 0 && requested !== null && selectedTotal.lessThan(requested)

  return {
    status: lots.status,
    error: lots.error,
    refetch: lots.refetch,
    candidates,
    selectedLotIds,
    toggleLot,
    clearSelection,
    selectedTotal,
    requested,
    isShort,
  }
}
