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
import { TasksPage } from '@/pages/tasks'

const qc = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' },
  { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'viewer' },
]

const tasks: TaskRow[] = [
  {
    id: 't1',
    title: '认领我',
    description: null,
    status: 'backlog',
    project_id: 'p1',
    requirement_id: null,
    assignee_id: null,
    assignee: null,
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
  },
  {
    id: 't2',
    title: '进行中任务',
    description: null,
    status: 'in_progress',
    project_id: 'p1',
    requirement_id: null,
    assignee_id: 'u2',
    assignee: 'agent-a',
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
  },
]

function renderTasks(projectList: ProjectRow[] = projects) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projectList)
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

describe('任务看板(当前项目)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('渲染五列看板与任务卡片', async () => {
    renderTasks()
    expect(await screen.findByText('认领我')).toBeInTheDocument()
    expect(screen.getByText('进行中任务')).toBeInTheDocument()
    expect(screen.getByText(/当前项目:demo/)).toBeInTheDocument()
    for (const label of ['待办', '实现中', '验收中', '已完成', '已取消']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    expect(screen.getByRole('button', { name: '认领' })).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/projects/p1/tasks?limit=100')
  })

  it('viewer 不可见新建按钮与认领按钮', async () => {
    renderTasks([projects[1]])
    expect(await screen.findByText('认领我')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建任务/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '认领' })).not.toBeInTheDocument()
  })

  it('editor 点击认领调用 claim 接口', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderTasks()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '认领' }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/claim')
  })

  it('无当前项目时展示空态引导', async () => {
    renderTasks([])
    expect(await screen.findByText('暂无当前项目,请在侧边栏选择项目')).toBeInTheDocument()
  })
})

describe('任务删除入口与自由流转', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('editor 卡片有删除入口,点击后二次确认再调删除接口', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderTasks()
    const user = (await import('@testing-library/user-event')).default
    const deleteButtons = await screen.findAllByRole('button', { name: '删除' })
    expect(deleteButtons.length).toBe(2)
    await user.click(deleteButtons[0])
    expect(await screen.findByText(/确认删除任务/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认删除' }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/delete')
  })

  it('viewer 无删除入口', async () => {
    renderTasks([projects[1]])
    expect(await screen.findByText('认领我')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument()
  })

  it('moveTask 走通用改状态端点(含直达已完成)', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    const { moveTask } = await import('@/pages/tasks')
    await moveTask('t1', 'done')
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/status', { status: 'done' })
    await moveTask('t2', 'cancelled')
    expect(api.post).toHaveBeenCalledWith('/tasks/t2/status', { status: 'cancelled' })
  })
})

describe('任务卡片状态下拉(ticket 10)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('编辑权卡片渲染状态下拉(五态),选择即调通用改状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderTasks()
    const user = (await import('@testing-library/user-event')).default
    const combos = await screen.findAllByRole('combobox', { name: '状态' })
    expect(combos.length).toBe(2)
    await user.click(combos[0])
    await user.click(await screen.findByRole('option', { name: '已完成' }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/status', { status: 'done' })
  })

  it('viewer 状态下拉禁用', async () => {
    renderTasks([projects[1]])
    expect(await screen.findByText('认领我')).toBeInTheDocument()
    const combos = screen.getAllByRole('combobox', { name: '状态' })
    for (const c of combos) expect(c).toBeDisabled()
  })
})

describe('新建任务对话框关联需求(ticket 10)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  const requirements = [
    {
      id: 'r1',
      title: '登录功能',
      description: null,
      status: 'backlog',
      project_id: 'p1',
      created_by: 'u1',
      created_at: '2026-08-01T00:00:00+00:00',
      updated_at: '2026-08-01T00:00:00+00:00',
      task_count: 0,
    },
  ]

  function renderWithRequirements() {
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve(projects)
      if (path.includes('/requirements')) return Promise.resolve({ items: requirements, next_cursor: null })
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

  it('选择需求后提交带 requirement_id', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderWithRequirements()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /新建任务/ }))
    await user.type(screen.getByLabelText('标题'), '承接任务')
    await user.click(await screen.findByRole('combobox', { name: '关联需求' }))
    await user.click(await screen.findByRole('option', { name: '登录功能' }))
    await user.click(screen.getByRole('button', { name: '创建' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p1/tasks', {
      title: '承接任务',
      description: null,
      requirement_id: 'r1',
    })
  })

  it('不选需求 = 独立任务(requirement_id null)', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderWithRequirements()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /新建任务/ }))
    await user.type(screen.getByLabelText('标题'), '独立任务')
    await user.click(screen.getByRole('button', { name: '创建' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p1/tasks', {
      title: '独立任务',
      description: null,
      requirement_id: null,
    })
  })
})
