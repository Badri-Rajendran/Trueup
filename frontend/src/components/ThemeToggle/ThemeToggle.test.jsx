import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider } from '../../contexts/ThemeContext.jsx'
import { ThemeToggle } from './ThemeToggle.jsx'

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  )
}

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  vi.restoreAllMocks()
})

describe('ThemeToggle', () => {
  it('renders, defaulting to system with the next state as its accessible name', () => {
    renderToggle()
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument()
  })

  it('cycles light -> dark -> system on click, applying data-theme and persisting each step', async () => {
    const user = userEvent.setup()
    renderToggle()
    const button = screen.getByRole('button')

    await user.click(button)
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(localStorage.getItem('trueup.theme.v1')).toBe('light')
    expect(button).toHaveAccessibleName('Switch to dark theme')

    await user.click(button)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('trueup.theme.v1')).toBe('dark')
    expect(button).toHaveAccessibleName('Switch to system theme')

    await user.click(button)
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem('trueup.theme.v1')).toBe('system')
    expect(button).toHaveAccessibleName('Switch to light theme')
  })

  it('falls back cleanly when localStorage.setItem throws (private mode)', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    const user = userEvent.setup()
    renderToggle()
    const button = screen.getByRole('button')

    await user.click(button)
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(button).toHaveAccessibleName('Switch to dark theme')
  })

  it('falls back to system when localStorage.getItem throws on mount', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    renderToggle()
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument()
  })
})
