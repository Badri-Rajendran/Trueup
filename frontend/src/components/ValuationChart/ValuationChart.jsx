import Decimal from 'decimal.js'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { formatDate, formatMoney } from '../../utils/format.js'
import { EmptyState } from '../EmptyState'
import './ValuationChart.css'

const VIEW_WIDTH = 600
const VIEW_HEIGHT = 160
const PADDING_Y = 12
const DRAW_DURATION_MS = 700

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handleChange = (event) => setReduced(event.matches)
    query.addEventListener('change', handleChange)
    return () => query.removeEventListener('change', handleChange)
  }, [])
  return reduced
}

/** One {x, y} pair per point, in the chart's own `viewBox` units — `preserveAspectRatio="none"` on
 * the `<svg>` lets it stretch to any container width without recomputing these. */
function buildCoordinates(points) {
  const values = points.map((point) => new Decimal(point.value))
  const min = Decimal.min(...values)
  const max = Decimal.max(...values)
  const span = max.minus(min)
  const usableHeight = VIEW_HEIGHT - PADDING_Y * 2

  return points.map((point, index) => {
    const x = (index / (points.length - 1)) * VIEW_WIDTH
    const ratio = span.isZero() ? 0.5 : new Decimal(point.value).minus(min).dividedBy(span).toNumber()
    const y = PADDING_Y + (1 - ratio) * usableHeight
    return { x, y }
  })
}

function pathFor(coordinates) {
  return coordinates.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(' ')
}

/**
 * Hand-rolled SVG line chart (no charting library, task-8-brief.md) for the Dashboard hero's live
 * valuation series. Pointer-move and arrow-key scrub report the hovered/focused point via
 * `onScrub(point | null)` — the caller (Dashboard hero) uses that to swap its balance readout
 * between "live" and "scrubbed day". `isProvisional` dashes the final segment, since the live
 * series' most recent point is today's still-forming close (S4/ADR 6) — there is no per-point
 * provisional flag on the wire, only the series-level one.
 */
export function ValuationChart({ points, isProvisional = false, onScrub }) {
  const containerRef = useRef(null)
  const pathRef = useRef(null)
  const [activeIndex, setActiveIndex] = useState(null)
  const reducedMotion = usePrefersReducedMotion()

  const hasSeries = points.length >= 2
  const coordinates = useMemo(() => (hasSeries ? buildCoordinates(points) : []), [points, hasSeries])

  const solidCoordinates = isProvisional && hasSeries ? coordinates.slice(0, -1) : coordinates
  const provisionalCoordinates = isProvisional && hasSeries ? coordinates.slice(-2) : []
  const solidPath = solidCoordinates.length >= 2 ? pathFor(solidCoordinates) : pathFor(coordinates)
  const provisionalPath = provisionalCoordinates.length === 2 ? pathFor(provisionalCoordinates) : ''

  // Single stroke-dashoffset "draw-in" on (re)mount — skipped entirely under reduced motion.
  useLayoutEffect(() => {
    const path = pathRef.current
    if (!path) return undefined
    if (reducedMotion) {
      path.style.transition = 'none'
      path.style.strokeDasharray = 'none'
      path.style.strokeDashoffset = '0'
      return undefined
    }
    const length = path.getTotalLength()
    path.style.transition = 'none'
    path.style.strokeDasharray = `${length}`
    path.style.strokeDashoffset = `${length}`
    const frame = requestAnimationFrame(() => {
      path.style.transition = `stroke-dashoffset ${DRAW_DURATION_MS}ms var(--ease-standard, ease)`
      path.style.strokeDashoffset = '0'
    })
    return () => cancelAnimationFrame(frame)
  }, [solidPath, reducedMotion])

  useEffect(() => {
    onScrub?.(activeIndex === null ? null : points[activeIndex])
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `points`/`onScrub` identity churn every fetch; re-run on index change only.
  }, [activeIndex])

  useEffect(() => {
    // A fresh fetch (e.g. a range switch) can shrink the series — clamp rather than point at nothing.
    setActiveIndex((prev) => (prev === null ? null : Math.min(prev, points.length - 1)))
  }, [points.length])

  if (!hasSeries) {
    return (
      <div className="tu-valuation-chart tu-valuation-chart--empty">
        <EmptyState
          title="Not enough history yet"
          description="Your value chart will appear once more days of activity are recorded."
        />
      </div>
    )
  }

  const indexFromClientX = (clientX) => {
    const rect = containerRef.current.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return Math.round(ratio * (points.length - 1))
  }

  const handlePointerMove = (event) => setActiveIndex(indexFromClientX(event.clientX))
  const handlePointerLeave = () => setActiveIndex(null)
  const handleBlur = () => setActiveIndex(null)

  const handleKeyDown = (event) => {
    const lastIndex = points.length - 1
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setActiveIndex((prev) => Math.max(0, (prev ?? lastIndex) - 1))
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      setActiveIndex((prev) => Math.min(lastIndex, (prev ?? lastIndex) + 1))
    } else if (event.key === 'Home') {
      event.preventDefault()
      setActiveIndex(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      setActiveIndex(lastIndex)
    }
  }

  const first = points[0]
  const last = points[points.length - 1]
  const ariaLabel = `Portfolio value chart, ${formatDate(first.as_of_date)} to ${formatDate(last.as_of_date)}: ${formatMoney(first.value)} to ${formatMoney(last.value)}`
  const active = activeIndex === null ? null : points[activeIndex]
  const activeCoordinate = activeIndex === null ? null : coordinates[activeIndex]

  return (
    <div
      ref={containerRef}
      className="tu-valuation-chart"
      role="img"
      aria-label={ariaLabel}
      tabIndex={0}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
    >
      <svg
        className="tu-valuation-chart__svg"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path ref={pathRef} className="tu-valuation-chart__line" d={solidPath} />
        {provisionalPath && (
          <path className="tu-valuation-chart__line tu-valuation-chart__line--provisional" d={provisionalPath} />
        )}
        {activeCoordinate && (
          <>
            <line
              className="tu-valuation-chart__guide"
              x1={activeCoordinate.x}
              y1="0"
              x2={activeCoordinate.x}
              y2={VIEW_HEIGHT}
            />
            <circle className="tu-valuation-chart__dot" cx={activeCoordinate.x} cy={activeCoordinate.y} r="3" />
          </>
        )}
      </svg>
      <p className="tu-visually-hidden" aria-live="polite">
        {active ? `${formatDate(active.as_of_date)}: ${formatMoney(active.value)}` : ''}
      </p>
    </div>
  )
}
