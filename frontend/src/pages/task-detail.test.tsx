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
    user: { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'member' },
    logout: vi.fn(),
  }),
}))

import { api, type ProjectRow, type TaskRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { TaskDetailPage } from '@/pages/task-detail'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' },
  { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'editor' },
]

const task: TaskRow = {
  id: 't1',
  title: '其他项目的任务',
  description: null,
  status: 'backlog',
  project_id: 'p2',
  requirement_id: null,
  assignee_id: null,
  assignee: null,
  created_by: 'u1',
  created_at: '2026-08-01T00:00:00+00:00',
  updated_at: '2026-08-01T00:00:00+00:00',
}

function renderDetail(projectList: ProjectRow[] = projects) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projectList)
    if (path === '/tasks/t1') return Promise.resolve(task)
    return Promise.resolve({ items: [] })
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/tasks/t1']}>
          <Routes>
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('任务详情(当前项目约束)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('任务属于其他项目时展示约束门与切换按钮', async () => {
    renderDetail()
    expect(await screen.findByText('该任务不属于当前项目「demo」')).toBeInTheDocument()
    expect(screen.queryByText('其他项目的任务')).not.toBeInTheDocument()
  })

  it('点击切换后当前项目变为任务所属项目并展示详情', async () => {
    renderDetail()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    expect(await screen.findByText('其他项目的任务')).toBeInTheDocument()
  })

  it('无当前项目时展示空态引导', async () => {
    renderDetail([])
    expect(await screen.findByText('暂无当前项目,请在侧边栏选择项目')).toBeInTheDocument()
  })
})

describe('任务详情操作按钮(ticket 09 通用改状态)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('编辑权下展示标记完成/取消,点击走通用改状态端点,无验收对话框', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    expect(await screen.findByText('其他项目的任务')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /标记完成/ }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/status', { status: 'done' })
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/status', { status: 'cancelled' })
    expect(screen.queryByRole('button', { name: /开工/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /提交验收/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /验收通过/ })).not.toBeInTheDocument()
  })
})
