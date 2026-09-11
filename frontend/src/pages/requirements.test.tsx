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
    REQUIREMENT_STATUSES: ['pending', 'backlog', 'in_progress', 'done', 'cancelled'],
    EXECUTION_REQUIREMENT_STATUSES: ['backlog', 'in_progress', 'done', 'cancelled'],
  }
})

import { api, type ProjectRow, type RequirementRow } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { NotificationProvider } from '@/components/ui/notification'
import { moveRequirement, RequirementsPage } from '@/pages/requirements'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const projects: ProjectRow[] = [
  { id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: 'viewer' },
  { id: 'p2', name: '网站改版', created_at: '2026-08-02T00:00:00Z', my_role: 'owner' },
]

const requirements: RequirementRow[] = [
  {
    id: 'r0',
    title: '等待产品确认',
    description: null,
    status: 'pending',
    project_id: 'p1',
    created_by: 'u1',
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
    task_count: 0,
  },
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

const customViews: FilterViewRow[] = [
  {
    id: 'v1',
    project_id: 'p1',
    user_id: 'u1',
    entity_type: 'requirement',
    name: '进行中',
    criteria: { statuses: ['backlog', 'in_progress'], view_mode: 'board' },
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
  },
  {
    id: 'v2',
    project_id: 'p1',
    user_id: 'u1',
    entity_type: 'requirement',
    name: '历史',
    criteria: { statuses: ['done'], view_mode: 'list' },
    created_at: '2026-08-01T00:00:00+00:00',
    updated_at: '2026-08-01T00:00:00+00:00',
  },
]

function lastUrl(match: (u: string) => boolean): string {
  const urls = vi.mocked(api.get).mock.calls.map((c) => String(c[0])).filter(match)
  return urls[urls.length - 1] ?? ''
}

function paramsOf(url: string): URLSearchParams {
  return new URLSearchParams((url.split('?')[1] ?? ''))
}

/** 最近一次需求列表请求的查询参数 */
const requirementParams = () => paramsOf(lastUrl((u) => u.includes('/requirements')))

interface RenderOptions {
  items?: RequirementRow[]
  nextCursor?: string | null
  views?: FilterViewRow[]
  withNotifications?: boolean
  mockGet?: (path: string) => Promise<unknown>
}

function renderRequirements(projectList: ProjectRow[] = projects, opts: RenderOptions = {}) {
  if (opts.mockGet) {
    vi.mocked(api.get).mockImplementation(opts.mockGet)
  } else {
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve(projectList)
      if (path.includes('/filter-views')) return Promise.resolve({ items: opts.views ?? [] })
      if (path.includes('/requirements')) {
        return Promise.resolve({ items: opts.items ?? requirements, next_cursor: opts.nextCursor ?? null })
      }
      return Promise.resolve({})
    })
  }
  const page = (
    <QueryClientProvider client={qc}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={['/requirements']}>
          <Routes>
            <Route path="/requirements" element={<RequirementsPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>
  )
  return render(opts.withNotifications ? <NotificationProvider>{page}</NotificationProvider> : page)
}

describe('需求列表页(当前项目)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('新建需求描述为单行且最多 512 字符', async () => {
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /新建需求/ }))
    const description = screen.getByLabelText('描述')
    expect(description.tagName).toBe('INPUT')
    expect(description).toHaveAttribute('maxlength', '512')
  })

  it('默认选中「近期活跃」:取第一个可见项目,首次加载带 updated_within_days=3 且以看板展示', async () => {
    renderRequirements()
    // 默认展示模式为看板:五列(含待确认)全部可见(REQ 9cac46ea)
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    for (const label of ['待确认', '待办', '实现中', '已完成', '已取消']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    expect(screen.getByText('等待产品确认')).toBeInTheDocument()
    expect(screen.getByText(/当前项目:demo/)).toBeInTheDocument()
    expect(screen.getByText('2 任务')).toBeInTheDocument()
    // 视图切换器:全部 / 近期活跃
    expect(screen.getByRole('button', { name: /全部/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /近期活跃/ })).toBeInTheDocument()
    // 首次列表请求带 updated_within_days=3 与 limit=20(cursor 分页契约)
    const params = requirementParams()
    expect(params.get('updated_within_days')).toBe('3')
    expect(params.get('limit')).toBe('20')
    // 个人视图列表按实体类型拉取
    expect(api.get).toHaveBeenCalledWith('/projects/p1/filter-views?entity_type=requirement')
  })

  it('新建需求表单草稿:输入自动暂存,清空草稿重置(REQ ff7a0aa2;重开恢复由任务对话框用例覆盖)', async () => {
    const user = (await import('@testing-library/user-event')).default
    renderRequirements([projects[1]])
    await user.click(await screen.findByRole('button', { name: /新建需求/ }))
    await user.type(screen.getByLabelText('标题'), '未提交的需求草稿')
    await user.type(screen.getByLabelText('描述'), '草稿描述')
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem('zeichen.draft.requirement:p2')!)).toEqual({ title: '未提交的需求草稿', description: '草稿描述' })
    })

    // 清空草稿:存储清除 + 表单重置
    await user.click(screen.getByRole('button', { name: '清空草稿' }))
    expect(localStorage.getItem('zeichen.draft.requirement:p2')).toBeNull()
    expect(screen.getByLabelText('标题')).toHaveValue('')
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

describe('筛选视图与视图切换器(默认「近期活跃」)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('切换到「全部」:无条件、展示模式恢复为列表;切回「近期活跃」恢复看板', async () => {
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /全部/ }))
    // 列表展示全部状态(含待确认),无看板列头
    expect(await screen.findByText('等待产品确认')).toBeInTheDocument()
    expect(screen.getByText('登录功能')).toBeInTheDocument()
    expect(screen.getByText('已验收需求')).toBeInTheDocument()
    await waitFor(() => {
      expect(requirementParams().has('updated_within_days')).toBe(false)
    })
    // 切回「近期活跃」:恢复看板(待确认列与卡片可见)并重新带时间窗口
    await user.click(screen.getByRole('button', { name: /近期活跃/ }))
    await waitFor(() => {
      expect(requirementParams().get('updated_within_days')).toBe('3')
      expect(screen.getByText('等待产品确认')).toBeInTheDocument()
      expect(screen.getAllByText('已取消').length).toBeGreaterThan(0) // 看板列头
    })
  })

  it('自定义视图:切换时恢复保存的展示模式与筛选条件', async () => {
    renderRequirements([projects[1]], { views: customViews })
    const user = (await import('@testing-library/user-event')).default
    // 「进行中」:view_mode=board + statuses=[backlog, in_progress]
    await user.click(await screen.findByRole('button', { name: '进行中' }))
    await waitFor(() => {
      expect(requirementParams().getAll('status').sort()).toEqual(['backlog', 'in_progress'])
      expect(screen.getAllByText('已取消').length).toBeGreaterThan(0) // 看板列头
    })
    // 「历史」:view_mode=list + statuses=[done]
    await user.click(screen.getByRole('button', { name: '历史' }))
    await waitFor(() => {
      expect(requirementParams().getAll('status')).toEqual(['done'])
      expect(screen.queryByText('已取消')).not.toBeInTheDocument() // 列表无看板列头
    })
    // 内置视图仍可切回
    await user.click(screen.getByRole('button', { name: /近期活跃/ }))
    await waitFor(() => expect(requirementParams().get('updated_within_days')).toBe('3'))
  })
})

describe('筛选条件下推 API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('状态多选:每个选中状态追加一个 status 参数', async () => {
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /状态/ }))
    await user.click(await screen.findByRole('checkbox', { name: '待办' }))
    await user.click(screen.getByRole('checkbox', { name: '已完成' }))
    await waitFor(() => {
      expect(requirementParams().getAll('status').sort()).toEqual(['backlog', 'done'])
    })
  })

  it('时间窗口与关键词筛选触发参数(关键词输入 autoComplete="off")', async () => {
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    const keyword = await screen.findByLabelText(/关键词/)
    expect(keyword).toHaveAttribute('autocomplete', 'off')
    await user.type(keyword, '登录')
    await user.keyboard('{Enter}')
    await user.selectOptions(screen.getByRole('combobox', { name: /时间窗口/ }), '7')
    await waitFor(() => {
      const params = requirementParams()
      expect(params.get('keyword')).toBe('登录')
      expect(params.get('updated_within_days')).toBe('7')
    })
  })
})

describe('个人视图管理', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('另存为对话框:名称必填且 autoComplete 合规,保存后 POST 个人视图', async () => {
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /另存为/ }))
    const dialog = await screen.findByRole('dialog')
    const nameInput = within(dialog).getByLabelText(/名称/)
    expect(nameInput).toBeRequired()
    expect(nameInput.getAttribute('autocomplete')).toBeTruthy() // AGENTS.md:禁止裸输入控件
    await user.type(nameInput, '我的需求视图')
    await user.click(within(dialog).getByRole('button', { name: /保存/ }))
    expect(api.post).toHaveBeenCalledWith(
      '/projects/p2/filter-views', // 当前项目为 p2(renderRequirements([projects[1]]))
      expect.objectContaining({
        entity_type: 'requirement',
        name: '我的需求视图',
        criteria: expect.objectContaining({ view_mode: 'board' }), // 当前「近期活跃」的展示模式
      }),
    )
  })

  it('修改个人视图:PATCH 更新名称与条件', async () => {
    renderRequirements([projects[1]], { views: [customViews[0]] })
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '视图操作' }))
    await user.click(await screen.findByRole('menuitem', { name: '修改' }))
    const dialog = await screen.findByRole('dialog')
    const nameInput = within(dialog).getByLabelText(/名称/)
    await user.clear(nameInput)
    await user.type(nameInput, '进行中(已保存)')
    await user.click(within(dialog).getByRole('button', { name: /保存/ }))
    expect(api.patch).toHaveBeenCalledWith('/filter-views/v1', expect.objectContaining({ name: '进行中(已保存)' }))
  })

  it('删除个人视图需二次确认,确认后调 DELETE', async () => {
    renderRequirements([projects[1]], { views: [customViews[0]] })
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: '视图操作' }))
    await user.click(await screen.findByRole('menuitem', { name: '删除' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/删除视图/)).toBeInTheDocument()
    // 取消不删除
    await user.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(api.delete).not.toHaveBeenCalled()
    // 再次进入并确认删除
    await user.click(screen.getByRole('button', { name: '视图操作' }))
    await user.click(await screen.findByRole('menuitem', { name: '删除' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /确认删除/ }))
    expect(api.delete).toHaveBeenCalledWith('/filter-views/v1')
  })
})

describe('分页与共用筛选结果', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('「加载更多」用 next_cursor 续拉并追加到当前结果', async () => {
    const page1 = { items: [requirements[0], requirements[1]], next_cursor: 'cursor-abc' }
    const page2 = { items: [requirements[2]], next_cursor: null }
    renderRequirements([projects[1]], {
      mockGet: (path: string) => {
        if (path === '/projects') return Promise.resolve([projects[1]])
        if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
        if (path.includes('/requirements')) {
          return Promise.resolve(String(path).includes('cursor=cursor-abc') ? page2 : page1)
        }
        return Promise.resolve({})
      },
    })
    const user = (await import('@testing-library/user-event')).default
    // 第一页:登录功能可见,已验收需求(第二页)尚未加载
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    expect(screen.queryByText('已验收需求')).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /加载更多/ }))
    // 续拉带 next_cursor,且保留既有筛选条件(updated_within_days=3)
    const cursorUrl = lastUrl((u) => u.includes('cursor=cursor-abc'))
    expect(cursorUrl).toContain('/projects/p2/requirements') // 当前项目为 p2(renderRequirements([projects[1]]))
    expect(paramsOf(cursorUrl).get('updated_within_days')).toBe('3')
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('cursor=cursor-abc'))
    // 第二页结果追加到同一列表
    expect(await screen.findByText('已验收需求')).toBeInTheDocument()
    // 无下一页后「加载更多」消失
    expect(screen.queryByRole('button', { name: /加载更多/ })).not.toBeInTheDocument()
  })

  it('看板与列表共用同一筛选结果', async () => {
    // mock 模拟服务端按 status 过滤,返回结果即筛选结果
    renderRequirements([projects[1]], {
      mockGet: (path: string) => {
        if (path === '/projects') return Promise.resolve([projects[1]])
        if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
        if (path.includes('/requirements')) {
          const params = new URLSearchParams(String(path).split('?')[1])
          const statuses = params.getAll('status')
          const items = statuses.length ? requirements.filter((r) => statuses.includes(r.status)) : requirements
          return Promise.resolve({ items, next_cursor: null })
        }
        return Promise.resolve({})
      },
    })
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /状态/ }))
    await user.click(await screen.findByRole('checkbox', { name: '待办' }))
    await waitFor(() => expect(requirementParams().getAll('status')).toEqual(['backlog']))
    await user.keyboard('{Escape}') // 关闭筛选弹层
    // 看板(默认展示模式):仅 backlog 需求(状态筛选由查询承担,与列无关)
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    expect(screen.queryByText('等待产品确认')).not.toBeInTheDocument()
    expect(screen.queryByText('已验收需求')).not.toBeInTheDocument()
    // 切到列表展示(同一筛选结果,不改变筛选条件)
    await user.click(screen.getByRole('button', { name: '列表' }))
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    expect(screen.queryByText('等待产品确认')).not.toBeInTheDocument()
    expect(screen.queryByText('已验收需求')).not.toBeInTheDocument()
  })
})

describe('需求执行看板(四列自由拖拽)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
    localStorage.clear()
  })

  it('看板默认展示五列(含待确认)且显示待确认需求,筛选条提供五态多选', async () => {
    renderRequirements([projects[1]])
    // 默认即看板:五列列头可见(含待确认),无「验收中」列
    for (const label of ['待确认', '待办', '实现中', '已完成', '已取消']) {
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0)
    }
    expect(screen.queryByText('验收中')).not.toBeInTheDocument()
    expect(screen.getByText('等待产品确认')).toBeInTheDocument()
    // 状态筛选为五态多选
    const user = (await import('@testing-library/user-event')).default
    await user.click(screen.getByRole('button', { name: /状态/ }))
    for (const label of ['待确认', '待办', '实现中', '已完成', '已取消']) {
      expect(await screen.findByRole('checkbox', { name: label })).toBeInTheDocument()
    }
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

  it('编辑权卡片渲染状态下拉(五态),选择即调通用改状态端点', async () => {
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderRequirements([projects[1]])
    const user = (await import('@testing-library/user-event')).default
    // 默认看板隐藏待确认需求,切到「全部」列表以覆盖全部卡片
    await user.click(await screen.findByRole('button', { name: /全部/ }))
    const combos = await screen.findAllByRole('combobox', { name: '状态' })
    expect(combos.length).toBe(3)
    await user.click(combos[0])
    await user.click(await screen.findByRole('option', { name: '已完成' }))
    expect(api.post).toHaveBeenCalledWith('/requirements/r0/status', { status: 'done' })
  })

  it('viewer 状态下拉禁用', async () => {
    renderRequirements()
    const user = (await import('@testing-library/user-event')).default
    await user.click(await screen.findByRole('button', { name: /全部/ }))
    expect(await screen.findByText('登录功能')).toBeInTheDocument()
    const combos = screen.getAllByRole('combobox', { name: '状态' })
    expect(combos.length).toBe(3)
    for (const c of combos) expect(c).toBeDisabled()
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
      renderRequirements([projects[1]], {
        withNotifications: true,
        mockGet: (path: string) => {
          if (path === '/projects') return Promise.resolve([projects[1]])
          if (path.includes('/filter-views')) return Promise.resolve({ items: [] })
          if (path.includes('/requirements')) return Promise.reject(new Error('需求加载失败'))
          return Promise.resolve({})
        },
      })
      expect(await screen.findByRole('alert')).toHaveTextContent('需求加载失败')
      expect(alertSpy).not.toHaveBeenCalled()
    } finally {
      alertSpy.mockRestore()
    }
  })

  it('状态变更失败走 ErrorNotification 而非 alert', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
    try {
      vi.mocked(api.post).mockRejectedValue(new Error('状态变更失败'))
      renderRequirements([projects[1]], { withNotifications: true })
      const user = (await import('@testing-library/user-event')).default
      await user.click(await screen.findByRole('button', { name: /全部/ }))
      const combos = await screen.findAllByRole('combobox', { name: '状态' })
      await user.click(combos[0])
      await user.click(await screen.findByRole('option', { name: '已完成' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('状态变更失败')
      expect(alertSpy).not.toHaveBeenCalled()
    } finally {
      alertSpy.mockRestore()
    }
  })
})
