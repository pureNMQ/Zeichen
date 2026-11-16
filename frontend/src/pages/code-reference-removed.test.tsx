import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { App } from '@/App'
import { NotificationProvider } from '@/components/ui/notification'

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
    REQUIREMENT_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
    TASK_STATUSES: ['backlog', 'in_progress', 'verifying', 'done', 'cancelled'],
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

function renderAtCodeReference() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve([])
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <NotificationProvider>
        <MemoryRouter initialEntries={['/code-reference']}>
          <App />
        </MemoryRouter>
      </NotificationProvider>
    </QueryClientProvider>,
  )
}

describe('API 参考文档模块移除', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('访问 /code-reference 不再渲染 API 参考页面，而是回到项目页', async () => {
    renderAtCodeReference()

    expect(await screen.findByRole('heading', { name: '项目' }, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '代码 API 参考' })).not.toBeInTheDocument()
  })
})
