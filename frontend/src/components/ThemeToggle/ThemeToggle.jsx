import { Icon } from '../Icon/Icon.jsx'
import { useTheme } from '../../contexts/ThemeContext.jsx'
import './ThemeToggle.css'

const NEXT_THEME = { light: 'dark', dark: 'system', system: 'light' }
const ICON_BY_THEME = { light: 'sun', dark: 'moon', system: 'monitor' }

/** Cycles light -> dark -> system -> light (design-system.md §2.2's explicit in-app toggle). */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const next = NEXT_THEME[theme]

  return (
    <button
      type="button"
      className="tu-theme-toggle"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
    >
      <Icon name={ICON_BY_THEME[theme]} />
    </button>
  )
}
