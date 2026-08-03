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
    REQUIREMENT_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
  }
})

import { api, type ProjectRow, type RequirementRow, type TaskRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { RequirementDetailPage } from '@/pages/requirement-detail'

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
  task_count: 0,
}

function renderDetail(projectList: ProjectRow[] = projects, extraMock?: (path: string) => unknown | undefined) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    const hit = extraMock?.(path)
    if (hit !== undefined) return Promise.resolve(hit)
    if (path === '/projects') return Promise.resolve(projectList)
    if (path === '/requirements/r1') return Promise.resolve(requirement)
    return Promise.resolve({ items: [] })
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/requirements/r1']}>
          <Routes>
            <Route path="/requirements/:id" element={<RequirementDetailPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
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

describe('需求详情操作(ticket 10 状态下拉)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('编辑权下详情页展示状态下拉(四态),选择走通用改状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    expect(await screen.findByText('其他项目的需求')).toBeInTheDocument()
    const combo = screen.getByRole('combobox', { name: '状态' })
    await user.click(combo)
    await user.click(await screen.findByRole('option', { name: '已完成' }))
    expect(api.post).toHaveBeenCalledWith('/requirements/r1/status', { status: 'done' })
    // 详情页无验收中(需求四态)
    await user.click(combo)
    expect(screen.queryByRole('option', { name: '验收中' })).not.toBeInTheDocument()
  })

  it('viewer 状态下拉禁用且无关联入口', async () => {
    const viewerProjects: ProjectRow[] = [
      { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'viewer' },
      { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'viewer' },
    ]
    renderDetail(projects, (path: string) => {
      if (path === '/projects') return viewerProjects
      return undefined
    })
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    expect(await screen.findByText('其他项目的需求')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '状态' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: '关联任务' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新建任务' })).not.toBeInTheDocument()
  })
})

describe('需求详情↔任务关联(ticket 10)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  const unattached: TaskRow[] = [
    {
      id: 't9',
      title: '游离任务',
      description: null,
      status: 'backlog',
      project_id: 'p2',
      requirement_id: null,
      assignee_id: null,
      assignee: null,
      created_by: 'u1',
      created_at: '2026-08-01T00:00:00+00:00',
      updated_at: '2026-08-01T00:00:00+00:00',
    },
  ]

  it('关联任务入口:列出未挂需求的任务,选择后 PATCH 挂到本需求', async () => {
    vi.mocked(api.patch).mockResolvedValue({ ok: true })
    renderDetail(projects, (path: string) => {
      if (path === '/projects/p2/tasks?limit=100') return { items: unattached, next_cursor: null }
      return undefined
    })
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    await user.click(await screen.findByRole('button', { name: '关联任务' }))
    expect(await screen.findByText('游离任务')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /游离任务/ }))
    expect(api.patch).toHaveBeenCalledWith('/tasks/t9', { requirement_id: 'r1' })
  })

  it('为该需求新建任务:对话框预选本需求,提交带 requirement_id', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderDetail()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '切换到该项目' }))
    await user.click(await screen.findByRole('button', { name: '新建任务' }))
    await user.type(screen.getByLabelText('标题'), '承接任务')
    await user.click(screen.getByRole('button', { name: '创建' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p2/tasks', {
      title: '承接任务',
      description: null,
      requirement_id: 'r1',
    })
  })
})
