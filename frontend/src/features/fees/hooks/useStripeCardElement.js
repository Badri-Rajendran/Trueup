import { useCallback, useEffect, useRef, useState } from 'react'
import { getStripe } from '../../../services/stripeLoader.js'

function readToken(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

// Stripe's Elements render inside an iframe and cannot read our CSS custom properties directly —
// this resolves the current theme's actual color values at call time. Re-run on every theme flip
// (see the useEffect below) so the field repaints instead of freezing at whichever theme was
// active when it first mounted.
function buildCardStyle() {
  return {
    base: {
      color: readToken('--color-text'),
      fontFamily: "'Public Sans', system-ui, -apple-system, sans-serif",
      fontSize: '15px',
      fontWeight: '400',
      // No `lineHeight` here -- Stripe's own docs discourage it (inconsistent across browsers)
      // in favor of sizing the field via the container's padding, which .tu-card-field__control
      // already does (var(--space-2) top/bottom against the 40px control-height floor, §7.2).
      iconColor: readToken('--color-text-secondary'),
      '::placeholder': { color: readToken('--color-text-muted') },
    },
    invalid: {
      color: readToken('--color-error'),
      iconColor: readToken('--color-error'),
    },
  }
}

/**
 * Owns the whole lifecycle of a single Stripe `card` Element: loading Stripe.js, mounting it into
 * `containerRef`, tracking ready/validation/focus state, keeping its style in sync with the app's
 * light/dark theme, and tearing it down on unmount. `onChange` fires on every Stripe `change`
 * event — `usePaymentMethod` uses it to clear a stale submit/error state as soon as the customer
 * edits the card (the fix for the form getting stuck after a save or a failure).
 */
export function useStripeCardElement({ onChange } = {}) {
  const containerRef = useRef(null)
  const stripeRef = useRef(null)
  const cardRef = useRef(null)
  const [status, setStatus] = useState('loading')
  const [cardError, setCardError] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    setLoadError(null)

    getStripe()
      .then((stripe) => {
        if (cancelled || !stripe || !containerRef.current) return

        const elements = stripe.elements()
        const card = elements.create('card', { style: buildCardStyle(), hidePostalCode: false })
        card.mount(containerRef.current)

        card.on('ready', () => {
          if (cancelled) return
          setStatus('ready')
        })
        card.on('change', (event) => {
          if (cancelled) return
          setCardError(event.error?.message ?? null)
          onChange?.()
        })
        card.on('focus', () => {
          if (containerRef.current) containerRef.current.dataset.focused = 'true'
        })
        card.on('blur', () => {
          if (containerRef.current) containerRef.current.dataset.focused = 'false'
        })

        stripeRef.current = stripe
        cardRef.current = card
      })
      .catch((error) => {
        if (cancelled) return
        setLoadError(error)
        setStatus('error')
      })

    return () => {
      cancelled = true
      cardRef.current?.unmount()
      cardRef.current?.destroy()
      cardRef.current = null
      stripeRef.current = null
    }
  }, [reloadKey, onChange])

  useEffect(() => {
    function syncTheme() {
      cardRef.current?.update({ style: buildCardStyle() })
    }

    // An explicit in-app theme toggle changes documentElement's data-theme attribute; the OS-level
    // preference changes independently. Both need to reach the iframe.
    const observer = new MutationObserver(syncTheme)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', syncTheme)

    return () => {
      observer.disconnect()
      media.removeEventListener('change', syncTheme)
    }
  }, [])

  const retry = useCallback(() => setReloadKey((key) => key + 1), [])

  return {
    containerRef,
    status,
    // Reading the refs at render time is safe here: they're only ever populated just before the
    // `card.on('ready', ...)` handler calls `setStatus('ready')`, which is what triggers this
    // render in the first place — by the time a consumer sees `status === 'ready'`, both refs are
    // already set.
    cardElement: cardRef.current,
    stripe: stripeRef.current,
    cardError,
    loadError,
    retry,
  }
}
