import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

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
    STATUS_LABEL: {
      pending: '待确认',
      backlog: '待办',
      in_progress: '实现中',
      verifying: '验收中',
      done: '已完成',
      cancelled: '已取消',
    },
    REQUIREMENT_STATUSES: ['pending', 'backlog', 'in_progress', 'done', 'cancelled'],
    TASK_STATUSES: ['backlog', 'in_progress', 'verifying', 'done', 'cancelled'],
  }
})

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'member' },
    logout: vi.fn(),
  }),
}))

import { api, type ProjectRow, type RequirementRow, type TaskRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { RequirementDetailPage } from '@/pages/requirement-detail'
import { TaskDetailPage } from '@/pages/task-detail'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' },
  { id: 'p2', name: '贼船', created_at: '2026-08-02T00:00:00Z', my_role: 'editor' },
]

// 存量 Markdown 描述(历史数据):必须按纯文本展示,不执行 Markdown 渲染。
const legacyRequirementDescription =
  '**扫码登录** 或 [密码登录](https://example.com/doc),见 `docs/auth.md`'
const legacyTaskDescription = '~~旧方案~~ 改用 **轮询**,配置见 [说明](https://example.com/cfg)'

const requirement: RequirementRow = {
  id: 'r1',
  title: '存量需求',
  description: legacyRequirementDescription,
  status: 'backlog',
  project_id: 'p2',
  created_by: 'u1',
  created_at: '2026-08-01T00:00:00+00:00',
  updated_at: '2026-08-01T00:00:00+00:00',
  task_count: 0,
}

const task: TaskRow = {
  id: 't1',
  title: '存量任务',
  description: legacyTaskDescription,
  status: 'backlog',
  project_id: 'p2',
  requirement_id: null,
  assignee_id: null,
  assignee: null,
  created_by: 'u1',
  created_at: '2026-08-01T00:00:00+00:00',
  updated_at: '2026-08-01T00:00:00+00:00',
}

function renderPage(path: string) {
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/requirements/:id" element={<RequirementDetailPage />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('需求/任务描述按纯文本展示(REQ-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
    localStorage.setItem('zeichen.currentProjectId', 'p2')
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve(projects)
      if (path === '/requirements/r1') return Promise.resolve(requirement)
      if (path === '/tasks/t1') return Promise.resolve(task)
      return Promise.resolve({ items: [] })
    })
  })

  it('需求详情把存量 Markdown 描述按纯文本展示,不渲染任何 Markdown 元素', async () => {
    renderPage('/requirements/r1')
    const description = await screen.findByText(legacyRequirementDescription)
    expect(description.closest('strong,em,del,code,pre,h1,h2,h3,ul,ol,li,a,img')).toBeNull()
    expect(description.textContent).toBe(legacyRequirementDescription)
  })

  it('任务详情把存量 Markdown 描述按纯文本展示,不渲染任何 Markdown 元素', async () => {
    renderPage('/tasks/t1')
    const description = await screen.findByText(legacyTaskDescription)
    expect(description.closest('strong,em,del,code,pre,h1,h2,h3,ul,ol,li,a,img')).toBeNull()
    expect(description.textContent).toBe(legacyTaskDescription)
  })
})
