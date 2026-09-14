import { describe, expect, it, vi, beforeEach } from 'vitest'
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

let mockRole: 'admin' | 'member' = 'admin'

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'u1', username: 'admin', is_agent: false, workspace_role: mockRole },
    logout: vi.fn(),
  }),
}))

import { api, type ProjectRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { AppShell } from '@/components/app-shell'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' },
  { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'viewer' },
]

function renderShell(role: 'admin' | 'member' = 'admin', initialPath = '/projects') {
  mockRole = role
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projects)
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <AppShell />
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('AppShell 侧边栏', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('导航分两区:团队功能 + 工作区,admin 见全部入口', async () => {
    renderShell('admin')
    expect(await screen.findByText('团队功能')).toBeInTheDocument()
    expect(screen.getByText('工作区')).toBeInTheDocument()
    // 任务入口已随独立任务面板移除(ADR 0003);Agent 管理页已随附属化移除(ADR 0004)
    expect(screen.queryByRole('link', { name: '任务' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Agent' })).not.toBeInTheDocument()
    for (const label of ['项目', '成员', '需求']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('附属化后 Agent 管理入口对任何角色都不存在', async () => {
    renderShell('member')
    expect(await screen.findByText('团队功能')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '项目' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '成员' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Agent' })).not.toBeInTheDocument()
  })

  it('文档为可折叠父项，展开后显示 Wiki 与词条，不再显示 API 子页', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    renderShell('admin')
    const documentToggle = await screen.findByRole('button', { name: '文档' })
    expect(documentToggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Wiki' })).not.toBeInTheDocument()

    await user.click(documentToggle)

    expect(documentToggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Wiki' })).toHaveAttribute('href', '/documents/wiki')
    expect(screen.getByRole('link', { name: '词条' })).toHaveAttribute('href', '/documents/glossary')
    expect(screen.queryByRole('link', { name: '代码 API 参考' })).not.toBeInTheDocument()
  })

  it('当前项目切换器:默认第一个可见项目,选择后持久化', async () => {
    const user = (await import('@testing-library/user-event')).default
    renderShell('admin')
    const trigger = await screen.findByRole('combobox')
    expect(trigger).toHaveTextContent('demo')
    await user.click(trigger)
    await user.click(await screen.findByRole('option', { name: '网站改版' }))
    expect(localStorage.getItem('zeichen.currentProjectId')).toBe('p2')
  })

  it('侧边栏底部用户按钮可收缩(flex-1 min-w-0),通知铃铛不溢出侧栏(REQ fa6e667e)', async () => {
    renderShell('admin')
    const bell = await screen.findByRole('button', { name: '通知' })
    const row = bell.closest('div.border-t')!
    const userButton = row.querySelector('button:not([aria-label])')!
    expect(userButton.className).toContain('flex-1')
    expect(userButton.className).toContain('min-w-0')
    expect(userButton.className).not.toContain('w-full')
    // 铃铛徽标锚定在按钮内沿,右移不超过行内边距(-right-1.5 < p-2)
    expect(bell.className).toContain('shrink-0')
  })
})
