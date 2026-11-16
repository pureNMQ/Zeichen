import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
    STATUS_LABEL: {},
  }
})

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'admin' },
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}))

import { api, type ProjectRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { ThemeProvider } from '@/lib/theme'
import { AppShell } from '@/components/app-shell'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' },
]

function renderShell() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projects)
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={['/projects']}>
            <AppShell />
          </MemoryRouter>
        </ThemeProvider>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

// 主题切换入口可位于顶栏,也可位于用户菜单(下拉菜单项渲染在 portal 中,需先打开菜单)
async function findThemeToggle() {
  const user = (await import('@testing-library/user-event')).default.setup()
  const direct =
    screen.queryByRole('button', { name: /主题/ }) ?? screen.queryByRole('menuitem', { name: /主题/ })
  if (direct) return direct
  const trigger = screen
    .getAllByRole('button')
    .find((b) => (b.textContent ?? '').includes('admin'))
  await user.click(trigger!)
  return screen.findByRole('menuitem', { name: /主题/ })
}

beforeEach(() => {
  vi.clearAllMocks()
  qc.clear()
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('主题切换入口(顶栏/用户菜单)', () => {
  it('存在可访问名称含「主题」的切换入口', async () => {
    renderShell()
    const toggle = await findThemeToggle()
    expect(toggle).toBeInTheDocument()
  })

  it('点击切换入口触发 toggle:html .dark 类切换并持久化', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    renderShell()
    expect(document.documentElement).not.toHaveClass('dark')

    await user.click(await findThemeToggle())
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('zeichen.theme')).toBe('dark')

    // 下拉菜单点击后可能关闭,重新定位入口再切回
    await user.click(await findThemeToggle())
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('zeichen.theme')).toBe('light')
  })
})
