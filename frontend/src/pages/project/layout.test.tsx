import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
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
  }
})

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { workspace_role: 'admin' } }),
}))

import { api, type ProjectMemberCandidate, type ProjectMemberRow } from '@/lib/api'
import { ProjectLayout } from '@/pages/project/layout'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const project = {
  id: 'p1',
  name: 'demo',
  created_at: '2026-08-01T00:00:00Z',
  my_role: 'owner',
}

const members: ProjectMemberRow[] = [
  { id: 'u1', username: 'admin', is_agent: false, role: 'owner', workspace_role: 'admin', is_current_user: true },
  { id: 'u2', username: 'bob', is_agent: false, role: 'viewer', workspace_role: 'member', is_current_user: false },
  { id: 'u3', username: 'alex', is_agent: false, role: 'editor', workspace_role: 'admin', is_current_user: false },
]

const candidates: ProjectMemberCandidate[] = [
  { id: 'u4', username: 'carol', is_agent: false, workspace_role: 'member' },
  { id: 'u5', username: 'new-admin', is_agent: false, workspace_role: 'admin' },
]

function renderLayout(myRole = 'owner', roster = members, loadCandidates = async () => candidates) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects/p1') return Promise.resolve({ ...project, my_role: myRole })
    if (path.includes('/members')) return Promise.resolve(roster)
    if (path.includes('/member_candidates')) return loadCandidates()
    if (path.includes('/files/associations?')) return Promise.resolve({ items: [], next_cursor: null })
    return Promise.resolve({})
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/projects/p1']}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectLayout />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function memberRow(name: string) {
  return (await screen.findByText(name, { exact: true })).closest('li')!
}

describe('项目详情页(成员授权)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
  })

  it('展示人类成员的名册角色及工作区管理员的实际权限', async () => {
    renderLayout()
    expect(await memberRow('admin')).toBeInTheDocument()
    for (const name of ['bob', 'alex']) {
      expect(await memberRow(name)).toBeInTheDocument()
    }
    expect(within(await memberRow('alex')).getByText(/拥有项目管理权限/)).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '类型' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /添加成员/ })).toBeInTheDocument()
  })

  it('改角色调用 PATCH 接口', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.patch).mockResolvedValue({ ok: true })
    renderLayout()
    const row = await memberRow('bob')
    await user.click(within(row).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'editor' }))
    expect(api.patch).toHaveBeenCalledWith('/projects/p1/members/u2', { role: 'editor' })
  })

  it('owner 角色显示禁用下拉框与转让入口，并要求当前密码', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderLayout()
    const ownerRow = await memberRow('admin')
    expect(within(ownerRow).getByRole('combobox')).toBeDisabled()
    await user.click(within(ownerRow).getByRole('button', { name: '转让 Owner' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'bob' }))
    await user.type(within(dialog).getByLabelText('当前密码'), 'admin-pass-1')
    await user.click(within(dialog).getByRole('button', { name: '确认转让 Owner' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p1/owner-transfer', {
      user_id: 'u2',
      password: 'admin-pass-1',
    })
  })

  it('移除成员调用 DELETE 接口(经 confirm)', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.delete).mockResolvedValue({ ok: true })
    renderLayout()
    const row = await memberRow('bob')
    await user.click(within(row).getByRole('button', { name: /移除 bob/ }))
    expect(api.delete).toHaveBeenCalledWith('/projects/p1/members/u2')
  })

  it('未入组管理员可添加人类管理员，附属 Agent 自动继承权限', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderLayout('owner', members.map((person) => ({ ...person, is_current_user: false })))
    expect(await screen.findByText(/在“添加成员”中选择自己/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '转让 Owner' })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /添加成员/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/附属 Agent 自动继承/)).toBeInTheDocument()
    await user.click(await within(dialog).findByRole('combobox', { name: '工作区成员' }))
    expect(screen.getByRole('option', { name: 'carol' })).toBeInTheDocument()
    await user.click(screen.getByRole('option', { name: 'new-admin（工作区管理员）' }))
    expect(within(dialog).getByText(/管理员始终拥有项目管理权限/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '添加' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p1/members', {
      user_id: 'u5',
      role: 'viewer',
    })
  })

  it('候选请求加载及失败时不显示空态，重试成功后才显示无人可选', async () => {
    const user = (await import('@testing-library/user-event')).default
    let fail!: (reason: Error) => void
    const pending = new Promise<ProjectMemberCandidate[]>((_, reject) => { fail = reject })
    const load = vi.fn().mockReturnValueOnce(pending).mockResolvedValue([])
    renderLayout('owner', members, load)
    await user.click(await screen.findByRole('button', { name: /添加成员/ }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(dialog.getByRole('status')).toHaveTextContent('正在加载')
    await act(async () => fail(new Error('请求失败')))
    expect(await dialog.findByRole('alert')).toHaveTextContent('加载失败')
    expect(dialog.queryByText(/没有可添加/)).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: '重新加载成员' }))
    expect(await dialog.findByText('没有可添加的人类成员。')).toBeInTheDocument()
    expect(dialog.getByRole('button', { name: '添加' })).toBeDisabled()
  })

  it('owner 重命名项目:提交调用 PATCH,名称更新', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.patch).mockResolvedValue({ ok: true })
    renderLayout()
    await user.click(await screen.findByRole('button', { name: '编辑项目信息' }))
    const dialog = await screen.findByRole('dialog')
    const input = within(dialog).getByLabelText('项目名')
    await user.clear(input)
    await user.type(input, '改版项目')
    await user.click(within(dialog).getByRole('button', { name: '保存' }))
    expect(api.patch).toHaveBeenCalledWith('/projects/p1', { name: '改版项目' })
  })

  it('非 owner 可以只读查看项目成员，隐藏管理控件', async () => {
    renderLayout('viewer')
    expect(await memberRow('admin')).toBeInTheDocument()
    expect(await memberRow('bob')).toBeInTheDocument()
    expect(screen.getByText('项目成员')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /添加成员/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /移除 bob/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '转让 Owner' })).not.toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/projects/p1/members')
  })
})
