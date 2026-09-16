import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionProvider } from '../contexts/SessionContext.jsx'
import { AppLayout } from './AppLayout.jsx'

// SessionProvider's mount-time refresh() must resolve/reject without a real network call. Reject
// (anonymous) is deliberate: it keeps EventStreamProvider's effect from ever calling connect(),
// which would instantiate `EventSource` -- not implemented in jsdom -- for a test that has nothing
// to do with the event stream.
vi.mock('../services/apiClient.js', () => ({
  apiClient: {
    get: vi.fn().mockRejectedValue(new Error('no session')),
    post: vi.fn(),
    setCsrfToken: vi.fn(),
    getCsrfToken: vi.fn(),
    clearCsrfToken: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}))

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SessionProvider>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={<div>destination content</div>} />
          </Route>
        </Routes>
      </SessionProvider>
    </MemoryRouter>,
  )
}

// This is the single highest-value test in the app shell rewrite: Chat (out of scope for any
// behavior change) sizes its internally-scrolling transcript by chaining `flex: 1; min-height: 0`
// up through `.tu-chat-page` -> `.tu-app-layout__main`. If a future edit to AppLayout drops any of
// these 4 properties from the element Outlet renders into, Chat silently starts scrolling the
// whole page instead of just its transcript -- this test is the only thing that would catch that.
describe('AppLayout main content wrapper', () => {
  it('carries the flex column + bounded-height contract Chat depends on to scroll internally', async () => {
    renderShell()
    const main = await screen.findByRole('main')

    expect(main).toHaveStyle({
      display: 'flex',
      flexDirection: 'column',
      flex: '1',
      minHeight: '0px',
    })
  })
})
