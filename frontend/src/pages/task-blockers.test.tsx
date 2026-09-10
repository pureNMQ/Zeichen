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
    TASK_STATUSES: ['backlog', 'in_progress', 'verifying', 'done', 'cancelled'],
    REQUIREMENT_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
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
import { TasksPage } from '@/pages/tasks'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

// REQ-7 契约(后端并行开发中,测试本地定义类型):
// TaskRow 新增 blocked: boolean 与 blocked_by: 前置摘要列表
// [{ id, title, status, resolved }](resolved = status === 'done')。
// UI 契约:受阻时任务详情与看板卡片出现含「受阻」字样的提示/标识;
// 详情页为每个未解除前置提供可跳转链接(href /tasks/{前置id})。
interface TaskBlockerSummary {
  id: string
  title: string
  status: string
  resolved: boolean
}
type TaskRowWithBlockers = TaskRow & {
  blocked: boolean
  blocked_by: TaskBlockerSummary[]
}

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' },
]

function baseTask(overrides: Partial<TaskRowWithBlockers>): TaskRowWithBlockers {
  return {
    id: 't1',
    title: '主任务',
    description: null,
    status: 'in_progress',
    project_id: 'p1',
    requirement_id: null,
    assignee_id: null,
    assignee: null,
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
    blocked: false,
    blocked_by: [],
    ...overrides,
  }
}

const blockedTask = baseTask({
  id: 't1',
  title: '被阻塞的主任务',
  blocked: true,
  blocked_by: [
    { id: 't2', title: '未完成前置任务', status: 'in_progress', resolved: false },
  ],
})

const unblockedTask = baseTask({
  id: 't1',
  title: '已解除阻塞的任务',
  blocked: false,
  blocked_by: [{ id: 't2', title: '已完成前置', status: 'done', resolved: true }],
})

function renderDetail(task: TaskRowWithBlockers) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projects)
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

function renderBoard(tasks: TaskRowWithBlockers[]) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projects)
    if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
    if (path.includes('/tasks')) return Promise.resolve({ items: tasks, next_cursor: null })
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/tasks']}>
          <Routes>
            <Route path="/tasks" element={<TasksPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('任务详情阻塞展示(REQ-7)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('受阻任务显示阻塞提示与未完成前置任务链接', async () => {
    renderDetail(blockedTask)
    await screen.findByText('被阻塞的主任务')
    expect(screen.getByText(/受阻/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /未完成前置任务/ })
    expect(link).toHaveAttribute('href', '/tasks/t2')
  })

  it('前置全部完成后阻塞提示解除(护栏:解除态不出现受阻提示)', async () => {
    renderDetail(unblockedTask)
    await screen.findByText('已解除阻塞的任务')
    expect(screen.queryByText(/受阻/)).not.toBeInTheDocument()
  })
})

describe('任务看板受阻标识(REQ-7)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('受阻任务卡片显示受阻标识', async () => {
    renderBoard([blockedTask])
    expect(await screen.findByText('被阻塞的主任务')).toBeInTheDocument()
    expect(screen.getByText(/受阻/)).toBeInTheDocument()
  })

  it('未受阻任务卡片不显示受阻标识(护栏)', async () => {
    renderBoard([unblockedTask])
    expect(await screen.findByText('已解除阻塞的任务')).toBeInTheDocument()
    expect(screen.queryByText(/受阻/)).not.toBeInTheDocument()
  })
})
