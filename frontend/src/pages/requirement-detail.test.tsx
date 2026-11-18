import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
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
    REQUIREMENT_STATUSES: ['pending', 'backlog', 'in_progress', 'verifying', 'done', 'cancelled'],
    TASK_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
  }
})

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'u1', username: 'admin', is_agent: false, workspace_role: 'member' },
    logout: vi.fn(),
  }),
}))

import { api, ApiError, type ProjectRow, type RequirementRow, type TaskRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { WorkEditorPage } from '@/pages/project/work-editor'
import { RequirementDetailPage } from '@/pages/requirement-detail'
import { NotificationProvider } from '@/components/ui/notification'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'viewer' },
  { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'editor' },
]

const requirement: RequirementRow = {
  id: 'r1',
  title: '其他项目的需求',
  description: null,
  status: 'backlog',
  project_id: 'p2',
  created_by: 'u1',
  created_at: '2026-08-01T00:00:00+00:00',
  updated_at: '2026-08-01T00:00:00+00:00',
  task_count: 3,
}

const pendingRequirement: RequirementRow = {
  ...requirement,
  title: '等待确认的需求',
  status: 'pending',
}

const panelTasks: TaskRow[] = [
  {
    id: 't1',
    title: '实现登录页',
    description: null,
    status: 'backlog',
    project_id: 'p2',
    requirement_id: 'r1',
    assignee_id: null,
    assignee: null,
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
  },
  {
    id: 't2',
    title: '联调接口',
    description: null,
    status: 'done',
    project_id: 'p2',
    requirement_id: 'r1',
    assignee_id: 'u1',
    assignee: 'admin',
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-02T00:00:00+00:00',
  },
  {
    id: 't3',
    title: '废弃方案',
    description: null,
    status: 'cancelled',
    project_id: 'p2',
    requirement_id: 'r1',
    assignee_id: null,
    assignee: null,
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-03T00:00:00+00:00',
  },
]

function renderDetail(
  projectList: ProjectRow[] = projects,
  extraMock?: (path: string) => unknown | undefined,
  initialEntry = '/requirements/r1',
) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    const hit = extraMock?.(path)
    if (hit !== undefined) return Promise.resolve(hit)
    if (path === '/projects') return Promise.resolve(projectList)
    if (path === '/requirements/r1' || path === '/projects/p2/requirements/r1') return Promise.resolve(requirement)
    if (path === '/projects/p2/tasks?requirement_id=r1&limit=100') return Promise.resolve({ items: panelTasks })
    if (path === '/tasks/t1') return Promise.resolve(panelTasks[0])
    return Promise.resolve({ items: [] })
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <NotificationProvider>
          <MemoryRouter initialEntries={[initialEntry]}>
            <Routes>
              <Route path="/requirements/:id" element={<RequirementDetailPage />} />
              <Route path="/projects/:projectId/requirements/:id/tasks/new" element={<WorkEditorPage kind="tasks" creating />} />
            </Routes>
          </MemoryRouter>
        </NotificationProvider>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

async function switchProject() {
  const user = (await import('@testing-library/user-event')).default
  await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
  expect(await screen.findByRole('link', { name: '返回需求' })).toBeInTheDocument()
  return user
}

describe('需求详情(当前项目约束)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('需求属于其他项目时展示约束门与切换按钮', async () => {
    renderDetail()
    expect(await screen.findByText('该需求不属于当前项目「demo」')).toBeInTheDocument()
    expect(screen.queryByText('其他项目的需求')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '切换到该项目' })).toBeInTheDocument()
  })

  it('点击切换后当前项目变为需求所属项目并展示详情', async () => {
    renderDetail()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    expect(await screen.findByText('其他项目的需求')).toBeInTheDocument()
    expect(localStorage.getItem('zeichen.currentProjectId')).toBe('p2')
  })

  it('无当前项目时展示空态引导', async () => {
    renderDetail([])
    expect(await screen.findByText('暂无当前项目,请在侧边栏选择项目')).toBeInTheDocument()
  })
})

describe('需求详情操作(状态下拉六态)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('编辑权下详情页状态下拉含验收中(需求六态),选择走通用改状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail()
    const user = await switchProject()
    const combo = screen.getAllByRole('combobox', { name: '状态' })[0]
    await user.click(combo)
    await user.click(await screen.findByRole('option', { name: '已完成' }))
    expect(api.post).toHaveBeenCalledWith('/requirements/r1/status', { status: 'done' })
    await user.click(combo)
    expect(screen.getByRole('option', { name: '验收中' })).toBeInTheDocument()
  })

  it('待确认需求可先拆任务也可直接确认', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail(projects, (path: string) => {
      if (path === '/requirements/r1') return pendingRequirement
      return undefined
    })
    const user = await switchProject()
    expect(await screen.findByText('等待确认的需求')).toBeInTheDocument()
    expect(screen.getByRole('button', { name:'新建任务' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '确认需求' }))
    expect(api.post).toHaveBeenCalledWith('/requirements/r1/status', { status: 'backlog' })
  })

  it('viewer 状态下拉禁用且无新建任务入口', async () => {
    const viewerProjects: ProjectRow[] = [
      { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'viewer' },
      { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'viewer' },
    ]
    renderDetail(projects, (path: string) => {
      if (path === '/projects') return viewerProjects
      return undefined
    })
    await switchProject()
    expect(screen.getAllByRole('combobox', { name: '状态' })[0]).toBeDisabled()
    expect(screen.queryByRole('button', { name: '新建任务' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '认领' })).not.toBeInTheDocument()
  })
})

describe('需求详情任务面板(ADR 0003)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('展示完成进度概览,已取消任务默认隐藏、可切换显示', async () => {
    renderDetail()
    await switchProject()
    expect(screen.getByText('任务(3)')).toBeInTheDocument()
    expect(screen.getByText('完成 1/3')).toBeInTheDocument()
    expect(screen.getByText('实现登录页')).toBeInTheDocument()
    expect(screen.getByText('联调接口')).toBeInTheDocument()
    expect(screen.queryByText('废弃方案')).not.toBeInTheDocument()
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button', { name: /显示已取消/ }))
    expect(screen.getByText('废弃方案')).toBeInTheDocument()
  })

  it('完整加载后续任务页，分列和完成数覆盖第二页', async () => {
    renderDetail(projects, path => {
      if (path === '/projects/p2/tasks?requirement_id=r1&limit=100') return { items:[panelTasks[0]], next_cursor:'next +/' }
      if (path === '/projects/p2/tasks?requirement_id=r1&limit=100&cursor=next%20%2B%2F') return { items:[panelTasks[1]], next_cursor:null }
      return undefined
    })
    await switchProject()
    expect(await screen.findByRole('button',{name:'打开任务 联调接口'})).toBeVisible()
    expect(screen.getByText('完成 1/2')).toBeVisible()
  })

  it.each([
    { role: 'viewer', assignee: 'u1', allowed: false },
    { role: 'editor', assignee: 'u2', allowed: false },
    { role: 'editor', assignee: 'u1', allowed: true },
    { role: 'owner', assignee: 'u2', allowed: true },
  ] as const)('$role 查看指派给 $assignee 的任务时看板和阅读页遵循同一权限', async ({ role, assignee, allowed }) => {
    localStorage.setItem('zeichen.currentProjectId', 'p2')
    const task = { ...panelTasks[0], assignee_id: assignee, assignee: '承接人' }
    renderDetail([{ ...projects[1], my_role: role }], path => {
      if (path.startsWith('/projects/p2/tasks?')) return { items: [task] }
      if (path === '/tasks/t1') return task
    })
    const open = await screen.findByRole('button', { name: '打开任务 实现登录页' })
    const card = open.closest<HTMLElement>('[data-slot="card"]')!
    const status = within(card).getByRole('combobox', { name: '状态' })
    const remove = within(card).queryByRole('button', { name: '删除' })
    expect(status.hasAttribute('disabled')).toBe(!allowed)
    expect(!!remove).toBe(allowed)
    expect(card.parentElement).toHaveAttribute('aria-disabled', String(!allowed))

    const user = (await import('@testing-library/user-event')).default
    await user.click(open)
    expect(await screen.findByRole('heading', { name: /实现登录页/ })).toBeVisible()
    expect(screen.getByRole('combobox', { name: '状态' }).hasAttribute('disabled')).toBe(!allowed)
    expect(!!screen.queryByRole('button', { name: '负责人：承接人' })).toBe(allowed)
    expect(!!screen.queryByRole('link', { name: '编辑任务' })).toBe(role !== 'viewer')
  })

  it('未指派任务可认领,认领失败显示可关闭的应用内通知', async () => {
    vi.mocked(api.post).mockImplementation((path: string) => {
      if (path === '/tasks/t1/claim') return Promise.reject(new ApiError(409, '任务已被认领'))
      return Promise.resolve({ ok: true })
    })
    renderDetail()
    await switchProject()
    const user = (await import('@testing-library/user-event')).default
    // 看板拖拽包装层(role=button)的可访问名包含整卡文本,动作按钮用精确名匹配
    await user.click(screen.getAllByRole('button', { name: '认领' })[0])
    expect(await screen.findByText('任务已被认领')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '关闭提示' }))
    expect(screen.queryByText('任务已被认领')).not.toBeInTheDocument()
  })

  it('点击任务打开任务阅读页(无评论区)', async () => {
    renderDetail()
    await switchProject()
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button', { name: '打开任务 实现登录页' }))
    expect(await screen.findByRole('heading',{name:/实现登录页/})).toBeVisible()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByLabelText('改指向需求')).toBeNull()
  })

  it('删除任务需二次确认', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail()
    await switchProject()
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getAllByRole('button', { name: '删除' })[0])
    expect(await screen.findByText('确认删除任务「实现登录页」?删除为软删,可从恢复入口找回。')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认删除' }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/delete')
  })

  it('删除确认期间任务改派给其他编辑者后收起确认', async () => {
    localStorage.setItem('zeichen.currentProjectId', 'p2')
    renderDetail()
    const user = (await import('@testing-library/user-event')).default
    const open = await screen.findByRole('button', { name: '打开任务 实现登录页' })
    const card = open.closest<HTMLElement>('[data-slot="card"]')!
    await user.click(within(card).getByRole('button', { name: '删除' }))
    expect(await screen.findByRole('button', { name: '确认删除' })).toBeVisible()
    await act(async () => {
      qc.setQueryData(['requirement-tasks', 'r1', 'p2'], {
        items: [{ ...panelTasks[0], assignee_id: 'u2', assignee: '其他编辑者' }],
      })
    })
    await waitFor(() => expect(screen.queryByRole('button', { name: '确认删除' })).not.toBeInTheDocument())
    expect(within(card).queryByRole('button', { name: '删除' })).not.toBeInTheDocument()
    await act(async () => {
      qc.setQueryData(['requirement-tasks', 'r1', 'p2'], { items: [panelTasks[0]] })
    })
    expect(await within(card).findByRole('button', { name: '删除' })).toBeEnabled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('为该需求新建任务:固定本需求,提交带 requirement_id', async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 't-new' })
    renderDetail()
    await switchProject()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '新建任务' }))
    await user.type(await screen.findByLabelText('标题'), '承接任务')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p2/tasks', expect.objectContaining({
      title: '承接任务',
      description: '',
      requirement_id: 'r1',
    }))
  })

  it('任务面板以看板分列展示:默认待办/实现中/已完成三列,已取消列随开关显隐', async () => {
    renderDetail()
    await switchProject()
    expect(screen.getAllByText('待办').length).toBeGreaterThan(0)
    expect(screen.getAllByText('实现中').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('已取消')).toHaveLength(0)
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button', { name: /显示已取消/ }))
    expect(screen.getAllByText('已取消').length).toBeGreaterThan(0)
    expect(screen.getByText('废弃方案')).toBeInTheDocument()
  })

  it('任务卡状态下拉改状态走任务状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail()
    await switchProject()
    const user = (await import('@testing-library/user-event')).default
    const combo = screen.getAllByRole('combobox', { name: '状态' })[1]
    await user.click(combo)
    await user.click(await screen.findByRole('option', { name: '已完成' }))
    expect(api.post).toHaveBeenCalledWith('/tasks/t1/status', { status: 'done' })
  })

  it('?task= 深链定位任务阅读页，返回后找到所属需求', async () => {
    localStorage.setItem('zeichen.currentProjectId','p2')
    renderDetail(projects, undefined, '/requirements/r1?task=t1')
    expect(await screen.findByRole('heading',{name:/实现登录页/})).toBeVisible()
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button',{name:/返回所属需求/}))
    expect(await screen.findByRole('button',{name:'打开任务 实现登录页'})).toBeVisible()
  })
})
