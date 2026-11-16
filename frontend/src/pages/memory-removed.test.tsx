import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { App } from '@/App'
import { AppShell } from '@/components/app-shell'
import { NotificationProvider } from '@/components/ui/notification'
import { CurrentProjectProvider } from '@/lib/current-project'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return {
    ApiError,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
    REQUIREMENT_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
    TASK_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
    STATUS_LABEL: {
      backlog: '待办',
      in_progress: '实现中',
      verifying: '验收中',
      done: '已完成',
      cancelled: '已取消',
    },
  }
})

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'admin' },
    loading: false,
    logout: vi.fn(),
  }),
}))

import { api } from '@/lib/api'

function mockProjects() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve([])
    return Promise.resolve({})
  })
}

describe('记忆系统下线(REQ-57)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockProjects()
  })

  it.each(['/memory', '/memory/sessions', '/cognee'])(
    '访问 %s 不再渲染记忆页面，而是回到项目页',
    async (entry) => {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      render(
        <QueryClientProvider client={qc}>
          <NotificationProvider>
            <MemoryRouter initialEntries={[entry]}>
              <App />
            </MemoryRouter>
          </NotificationProvider>
        </QueryClientProvider>,
      )

      expect(await screen.findByRole('heading', { name: '项目' }, { timeout: 3000 })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: /长期记忆|会话缓存|Cognee/ })).not.toBeInTheDocument()
    },
  )

  it('侧边栏与 api 客户端不再有任何记忆入口', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={qc}>
        <NotificationProvider>
          <CurrentProjectProvider>
            <MemoryRouter initialEntries={['/projects']}>
              <AppShell />
            </MemoryRouter>
          </CurrentProjectProvider>
        </NotificationProvider>
      </QueryClientProvider>,
    )

    const navText = container.querySelector('nav')?.textContent ?? ''
    expect(navText).not.toContain('记忆')
    expect(navText).not.toContain('Cognee')
  })
})
