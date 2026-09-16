import { createContext, useContext, useEffect, useState } from 'react'

const ThemeContext = createContext(undefined)

const STORAGE_KEY = 'trueup.theme.v1'
const VALID_THEMES = ['light', 'dark', 'system']

function readStoredTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return VALID_THEMES.includes(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

function applyTheme(theme) {
  if (theme === 'system') {
    document.documentElement.removeAttribute('data-theme')
  } else {
    document.documentElement.setAttribute('data-theme', theme)
  }
}

/**
 * Explicit in-app theme toggle, persisted per browser (design-system.md §2.2). `'system'` defers to
 * the OS `prefers-color-scheme` media query already wired into tokens.css; `'light'`/`'dark'` pin it
 * via `data-theme`, which tokens.css's explicit-toggle block reads.
 */
export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readStoredTheme)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const setTheme = (next) => {
    setThemeState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Private mode or storage-disabled browser -- theme still applies for this session.
    }
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
