import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { App } from '@/App'
import { AppShell } from '@/components/app-shell'
import { CurrentProjectProvider } from '@/lib/current-project'
import { NotificationProvider } from '@/components/ui/notification'
import { MANUAL_CHAPTERS } from '@/manual/content'

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

type MockUser = { id: string; username: string; is_agent: boolean; workspace_role: 'admin' | 'member' }

let mockUser: MockUser | null = { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'admin' }

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: mockUser,
    loading: false,
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}))

import { api, type ProjectRow } from '@/lib/api'

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' },
]

function renderAppAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(api.get).mockImplementation((requestPath: string) => {
    if (requestPath === '/auth/bootstrap') return Promise.resolve({ needs_bootstrap: false })
    if (requestPath === '/projects') return Promise.resolve([])
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <NotificationProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </NotificationProvider>
    </QueryClientProvider>,
  )
}

function renderShell(role: 'admin' | 'member' = 'admin') {
  mockUser = { id: 'u1', username: 'admin', is_agent: false, workspace_role: role }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.mocked(api.get).mockImplementation((requestPath: string) => {
    if (requestPath === '/projects') return Promise.resolve(projects)
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/projects']}>
          <AppShell />
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

describe('使用手册路由', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockUser = { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'admin' }
  })

  it('登录后访问 /manual 渲染使用手册页面', async () => {
    renderAppAt('/manual')
    expect(await screen.findByRole('heading', { name: '使用手册' })).toBeInTheDocument()
  })

  it('未登录访问 /manual 不可见,重定向到登录页', async () => {
    mockUser = null
    renderAppAt('/manual')
    expect(await screen.findByLabelText('账号')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '使用手册' })).not.toBeInTheDocument()
  })
})

describe('使用手册工作区级入口', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockUser = { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'admin' }
  })

  it('侧边栏存在「使用手册」入口且指向 /manual', async () => {
    renderShell('admin')
    const link = await screen.findByRole('link', { name: '使用手册' })
    expect(link).toHaveAttribute('href', '/manual')
  })

  it('普通成员同样可见「使用手册」入口', async () => {
    renderShell('member')
    const link = await screen.findByRole('link', { name: '使用手册' })
    expect(link).toHaveAttribute('href', '/manual')
  })
})

describe('手册目录导航', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockUser = { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'admin' }
  })

  it('侧边栏目录渲染全部章节且锚点指向章节 id', async () => {
    renderAppAt('/manual')
    const nav = await screen.findByRole('navigation', { name: '手册目录' })
    const links = within(nav).getAllByRole('link')
    for (const chapter of MANUAL_CHAPTERS) {
      const hit = links.find(
        (link) =>
          (link.getAttribute('href') ?? '').includes(`#${chapter.id}`) &&
          (link.textContent ?? '').includes(chapter.title),
      )
      expect(hit, `目录缺少章节「${chapter.title}」的锚点`).toBeDefined()
    }
  })

  it('点击章节锚点可查看对应章节内容', async () => {
    const user = userEvent.setup()
    renderAppAt('/manual')
    const nav = await screen.findByRole('navigation', { name: '手册目录' })
    const chapter = MANUAL_CHAPTERS[1] ?? MANUAL_CHAPTERS[0]
    const link = within(nav)
      .getAllByRole('link')
      .find((item) => (item.textContent ?? '').includes(chapter.title))
    expect(link).toBeDefined()
    await user.click(link!)
    expect(screen.getByRole('heading', { name: new RegExp(escapeRegExp(chapter.title)) })).toBeInTheDocument()
  })
})
