import '@testing-library/jest-dom'

// jsdom has no real implementation of matchMedia -- needed by anything reading
// prefers-color-scheme or prefers-reduced-motion.
window.matchMedia =
  window.matchMedia ||
  function matchMedia(query) {
    return {
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }
  }
