import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
import { TasksPage } from '@/pages/tasks'
import { NotificationProvider } from '@/components/ui/notification'

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

// 契约:GET /projects/{id}/filter-views 返回的个人视图行(后端并行开发中,测试本地定义类型)
interface FilterViewRow {
  id: string
  project_id: string
  user_id: string
  entity_type: 'requirement' | 'task'
  name: string
  criteria: {
    statuses?: string[]
    updated_within_days?: number
    keyword?: string
    assignee_id?: string
    view_mode?: 'board' | 'list'
  }
  created_at: string
  updated_at: string
}

function lastUrl(match: (u: string) => boolean): string {
  const urls = vi.mocked(api.get).mock.calls.map((c) => String(c[0])).filter(match)
  return urls[urls.length - 1] ?? ''
}

function paramsOf(url: string): URLSearchParams {
  return new URLSearchParams((url.split('?')[1] ?? ''))
}

/** 最近一次任务列表请求的查询参数 */
const taskParams = () => paramsOf(lastUrl((u) => u.includes('/tasks')))

interface RenderOptions {
  taskList?: TaskRow[]
  views?: FilterViewRow[]
  withNotifications?: boolean
  mockGet?: (path: string) => Promise<unknown>
}

function renderTasks(projectList: ProjectRow[] = projects, opts: RenderOptions = {}) {
  if (opts.mockGet) {
    vi.mocked(api.get).mockImplementation(opts.mockGet)
  } else {
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve(projectList)
      if (path.includes('/filter-views')) return Promise.resolve({ items: opts.views ?? [] })
      if (path.includes('/tasks')) return Promise.resolve({ items: opts.taskList ?? tasks, next_cursor: null })
      return Promise.resolve({})
    })
  }
  const page = (
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/tasks']}>
          <Routes>
            <Route path="/tasks" element={<TasksPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>
  )
  return render(opts.withNotifications ? <NotificationProvider>{page}</NotificationProvider> : page)
}

describe('任务看板(当前项目)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('默认选中「近期活跃」:渲染五列看板,首次加载带 updated_within_days=3 与 limit=20', async () => {
    renderTasks()
    expect(await screen.findByText('认领我')).toBeInTheDocument()
    expect(screen.getByText('进行中任务')).toBeInTheDocument()
    expect(screen.getByText(/当前项目:demo/)).toBeInTheDocument()
    for (const label of ['待办', '实现中', '验收中', '已完成', '已取消']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    expect(screen.getByRole('button', { name: '认领' })).toBeInTheDocument()
    // 视图切换器:全部 / 近期活跃
    expect(screen.getByRole('button', { name: /全部/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /近期活跃/ })).toBeInTheDocument()
    // 首次列表请求带 updated_within_days=3 与 limit=20(cursor 分页契约)
    const params = taskParams()
    expect(params.get('updated_within_days')).toBe('3')
    expect(params.get('limit')).toBe('20')
    expect(api.get).toHaveBeenCalledWith('/projects/p1/filter-views?entity_type=task')
  })

  it('切换到「全部」:展示模式恢复为列表;切回「近期活跃」恢复看板', async () => {
    renderTasks()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /全部/ }))
    // 列表模式:无看板列头(「验收中」列头消失),任务卡片仍渲染
    expect(await screen.findByText('认领我')).toBeInTheDocument()
    await waitFor(() => {
      expect(taskParams().has('updated_within_days')).toBe(false)
      expect(screen.queryByText('验收中')).not.toBeInTheDocument()
    })
    // 切回「近期活跃」:恢复看板(五列列头回归)并重新带时间窗口
    await user.click(screen.getByRole('button', { name: /近期活跃/ }))
    await waitFor(() => {
      expect(taskParams().get('updated_within_days')).toBe('3')
      expect(screen.getAllByText('验收中').length).toBeGreaterThan(0)
    })
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

  it('认领失败显示可关闭的应用内通知', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('认领失败'))
    renderTasks(projects, { withNotifications: true })
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '认领' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('认领失败')
    await user.click(screen.getByRole('button', { name: '关闭提示' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('无当前项目时展示空态引导', async () => {
    renderTasks([])
    expect(await screen.findByText('暂无当前项目,请在侧边栏选择项目')).toBeInTheDocument()
  })

  it('空任务只在列表模式显示提示', async () => {
    renderTasks(projects, { taskList: [] })
    await screen.findByText('待办')
    expect(screen.queryByText('暂无任务')).not.toBeInTheDocument()
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button', { name: '列表' }))
    expect(await screen.findByText('暂无任务')).toBeInTheDocument()
  })
})

describe('任务筛选(负责人)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('负责人筛选:选择负责人后追加 assignee_id 参数', async () => {
    const members = [
      {
        id: 'u1',
        username: 'admin',
        nickname: null,
        role: 'owner',
        created_at: '2026-08-01T00:00:00Z',
        is_bootstrap: false,
        is_self: true,
        has_password: true,
      },
      {
        id: 'u2',
        username: 'agent-a',
        nickname: null,
        role: 'editor',
        created_at: '2026-08-01T00:00:00Z',
        is_bootstrap: false,
        is_self: false,
        has_password: false,
      },
    ]
    renderTasks(projects, {
      mockGet: (path: string) => {
        if (path === '/projects') return Promise.resolve(projects)
        if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
        if (path.includes('/members')) return Promise.resolve(members)
        if (path.includes('/tasks')) return Promise.resolve({ items: tasks, next_cursor: null })
        return Promise.resolve({})
      },
    })
    const user = (await import('@testing-library/user-event')).default
    await user.selectOptions(await screen.findByRole('combobox', { name: /负责人/ }), 'u2')
    await waitFor(() => {
      expect(taskParams().get('assignee_id')).toBe('u2')
    })
  })
})

describe('任务页个人视图(另存为)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('另存为对话框:名称必填且 autoComplete 合规,以 entity_type=task 保存', async () => {
    renderTasks()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /另存为/ }))
    const dialog = await screen.findByRole('dialog')
    const nameInput = within(dialog).getByLabelText(/名称/)
    expect(nameInput).toBeRequired()
    expect(nameInput.getAttribute('autocomplete')).toBeTruthy() // AGENTS.md:禁止裸输入控件
    await user.type(nameInput, '我的任务视图')
    await user.click(within(dialog).getByRole('button', { name: /保存/ }))
    expect(api.post).toHaveBeenCalledWith(
      '/projects/p1/filter-views',
      expect.objectContaining({
        entity_type: 'task',
        name: '我的任务视图',
        criteria: expect.objectContaining({ view_mode: 'board' }),
      }),
    )
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
      if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
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

  it('新建任务描述最多 512 字符', async () => {
    renderWithRequirements()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /新建任务/ }))
    expect(screen.getByLabelText('描述')).toHaveAttribute('maxlength', '512')
  })
})

describe('错误反馈(ErrorNotification,禁用 alert)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('列表加载失败显示 ErrorNotification 而非 alert', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    try {
      renderTasks(projects, {
        withNotifications: true,
        mockGet: (path: string) => {
          if (path === '/projects') return Promise.resolve(projects)
          if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
          if (path.includes('/tasks')) return Promise.reject(new Error('任务加载失败'))
          return Promise.resolve({})
        },
      })
      expect(await screen.findByRole('alert')).toHaveTextContent('任务加载失败')
      expect(alertSpy).not.toHaveBeenCalled()
    } finally {
      alertSpy.mockRestore()
    }
  })
})
