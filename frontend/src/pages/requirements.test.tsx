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

import { api, type ProjectRow, type RequirementRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { moveRequirement, RequirementsPage } from '@/pages/requirements'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'viewer' },
  { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'owner' },
]

const requirements: RequirementRow[] = [
  {
    id: 'r1',
    title: '登录功能',
    description: null,
    status: 'backlog',
    project_id: 'p1',
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
    task_count: 2,
  },
  {
    id: 'r2',
    title: '已验收需求',
    description: null,
    status: 'done',
    project_id: 'p1',
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
    task_count: 0,
  },
]

function renderRequirements(projectList: ProjectRow[] = projects) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve(projectList)
    if (path.includes('/requirements')) return Promise.resolve({ items: requirements, next_cursor: null })
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/requirements']}>
          <Routes>
            <Route path="/requirements" element={<RequirementsPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('需求列表页(当前项目)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('默认取第一个可见项目并渲染需求列表', async () => {
    renderRequirements()
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    expect(screen.getByText('已验收需求')).toBeInTheDocument()
    expect(screen.getByText(/当前项目:demo/)).toBeInTheDocument()
    expect(screen.getAllByText('待办').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0)
    expect(screen.getByText('2 任务')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/projects/p1/requirements?limit=100')
  })

  it('viewer 不可见新建/删除按钮', async () => {
    renderRequirements()
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /新建需求/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument()
  })

  it('owner 可见新建/删除按钮', async () => {
    renderRequirements([projects[1]])
    expect(await screen.findByRole('button', { name: /新建需求/ })).toBeInTheDocument()
  })

  it('无当前项目(成员未加入任何项目)时展示空态引导', async () => {
    renderRequirements([])
    expect(await screen.findByText('暂无当前项目,请在侧边栏选择项目')).toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/requirements'))
  })
})

describe('需求看板(四列自由拖拽)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('editor 看板渲染四列(无验收中)且状态过滤无验收中', async () => {
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '看板' }))
    expect((await screen.findAllByText('待办')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('实现中').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已取消').length).toBeGreaterThan(0)
    expect(screen.queryByText('验收中')).not.toBeInTheDocument()
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['全部状态', '待办', '实现中', '已完成', '已取消'])
  })

  it('viewer 看板不可拖拽(无 canDrag 卡片交互)仍可渲染', async () => {
    renderRequirements()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '看板' }))
    expect((await screen.findAllByText('待办')).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /新建需求/ })).not.toBeInTheDocument()
  })

  it('moveRequirement 走通用改状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    await moveRequirement('r1', 'done')
    expect(api.post).toHaveBeenCalledWith('/requirements/r1/status', { status: 'done' })
    await moveRequirement('r2', 'cancelled')
    expect(api.post).toHaveBeenCalledWith('/requirements/r2/status', { status: 'cancelled' })
  })
})

describe('需求卡片状态下拉(ticket 10)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('编辑权卡片渲染状态下拉(四态),选择即调通用改状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    const combos = await screen.findAllByRole('combobox', { name: '状态' })
    expect(combos.length).toBe(2)
    await user.click(combos[0])
    await user.click(await screen.findByRole('option', { name: '已完成' }))
    expect(api.post).toHaveBeenCalledWith('/requirements/r1/status', { status: 'done' })
  })

  it('viewer 状态下拉禁用', async () => {
    renderRequirements()
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    const combos = screen.getAllByRole('combobox', { name: '状态' })
    expect(combos.length).toBe(2)
    for (const c of combos) expect(c).toBeDisabled()
  })
})
