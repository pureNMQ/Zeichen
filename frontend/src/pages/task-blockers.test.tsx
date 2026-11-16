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
  withProject: (path: string) => path,
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
    TASK_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
    REQUIREMENT_STATUSES: ['pending', 'backlog', 'in_progress', 'verifying', 'done', 'cancelled'],
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
import { TaskDetailDialog } from '@/components/task-detail-dialog'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

// REQ-7 契约 + ADR 0003:任务详情为弹窗(无独立页面);
// 受阻任务显示受阻标识与未完成前置;无评论区。

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

function baseTask(overrides: Partial<TaskRowWithBlockers>): TaskRowWithBlockers {
  return {
    id: 't1',
    title: '主任务',
    description: null,
    status: 'in_progress',
    project_id: 'p1',
    requirement_id: 'r1',
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
  title: '被阻塞的主任务',
  blocked: true,
  blocked_by: [{ id: 't2', title: '未完成前置任务', status: 'in_progress', resolved: false }],
})

const unblockedTask = baseTask({
  title: '已解除阻塞的任务',
  blocked: false,
  blocked_by: [{ id: 't2', title: '已完成前置', status: 'done', resolved: true }],
})

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' },
]

function renderDialog(task: TaskRowWithBlockers) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/tasks/t1') return Promise.resolve(task)
    if (path === '/projects') return Promise.resolve(projects)
    if (path === '/projects/p1/tasks?limit=100') {
      return Promise.resolve({ items: [task] })
    }
    return Promise.resolve({ items: [] })
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter>
          <TaskDetailDialog task={task} open onOpenChange={vi.fn()} />
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('任务详情弹窗阻塞展示(REQ-7 / ADR 0003)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
    localStorage.setItem('zeichen.currentProjectId', 'p1')
  })

  it('受阻任务显示受阻标识与未完成前置标题', async () => {
    renderDialog(blockedTask)
    await screen.findByText('被阻塞的主任务')
    expect(screen.getByText(/受阻/)).toBeInTheDocument()
    expect(screen.getAllByText('未完成前置任务').length).toBeGreaterThan(0)
  })

  it('前置全部完成后阻塞提示解除(护栏:解除态不出现受阻提示)', async () => {
    renderDialog(unblockedTask)
    await screen.findByText('已解除阻塞的任务')
    expect(screen.queryByText(/受阻/)).not.toBeInTheDocument()
    expect(screen.getByText('已完成前置（已完成）')).toBeInTheDocument()
  })

  it('弹窗无评论区(任务评论已取消)', async () => {
    renderDialog(blockedTask)
    await screen.findByText('被阻塞的主任务')
    expect(screen.queryByPlaceholderText(/评论/)).not.toBeInTheDocument()
  })

  it('编辑权下可维护阻塞依赖:移除前置整体替换 blocked_by', async () => {
    vi.mocked(api.patch).mockResolvedValue({ ok: true })
    renderDialog(blockedTask)
    await screen.findByText('被阻塞的主任务')
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button', { name: '移除前置 未完成前置任务' }))
    expect(api.patch).toHaveBeenCalledWith('/tasks/t1', { blocked_by: [] })
  })
})
