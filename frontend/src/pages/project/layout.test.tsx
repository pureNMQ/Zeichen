import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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

import { api, type ProjectMemberRow } from '@/lib/api'
import { ProjectLayout } from '@/pages/project/layout'

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const project = {
  id: 'p1',
  name: 'demo',
  created_at: '2026-08-01T00:00:00Z',
  my_role: 'owner',
}

const members: ProjectMemberRow[] = [
  { id: 'u1', username: 'admin', is_agent: false, role: 'owner' },
  { id: 'u2', username: 'bob', is_agent: false, role: 'viewer' },
  { id: 'u3', username: 'agent-a', is_agent: true, role: 'editor' },
]

const candidates: ProjectMemberRow[] = [
  { id: 'u4', username: 'carol', is_agent: false, role: 'viewer' },
  { id: 'u5', username: 'agent-b', is_agent: true, role: 'viewer' },
]

function renderLayout(myRole = 'owner') {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects/p1') return Promise.resolve({ ...project, my_role: myRole })
    if (path.includes('/members')) return Promise.resolve(members)
    if (path.includes('/member_candidates')) return Promise.resolve(candidates)
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

describe('项目详情页(成员授权)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    qc.clear()
  })

  it('owner 看到成员列表:角色、类型徽标、操作按钮', async () => {
    renderLayout()
    expect(await screen.findByRole('row', { name: /admin/ })).toBeInTheDocument()
    for (const name of ['bob', 'agent-a']) {
      expect(screen.getByRole('row', { name: new RegExp(name) })).toBeInTheDocument()
    }
    expect(screen.getAllByText('Agent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('成员').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /添加成员/ })).toBeInTheDocument()
  })

  it('改角色调用 PATCH 接口', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.patch).mockResolvedValue({ ok: true })
    renderLayout()
    const row = await screen.findByRole('row', { name: /bob/ })
    await user.click(within(row).getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: 'editor' }))
    expect(api.patch).toHaveBeenCalledWith('/projects/p1/members/u2', { role: 'editor' })
  })

  it('移除成员调用 DELETE 接口(经 confirm)', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.delete).mockResolvedValue({ ok: true })
    renderLayout()
    const row = await screen.findByRole('row', { name: /bob/ })
    await user.click(within(row).getByRole('button', { name: /移除 bob/ }))
    expect(api.delete).toHaveBeenCalledWith('/projects/p1/members/u2')
  })

  it('添加成员:候选人来自工作区成员与 Agent,提交调用 POST', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    renderLayout()
    await user.click(await screen.findByRole('button', { name: /添加成员/ }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('carol')).toBeInTheDocument()
    expect(await within(dialog).findByText('agent-b (Agent)')).toBeInTheDocument()
    await user.click(within(dialog).getAllByRole('combobox')[0])
    await user.click(await screen.findByRole('option', { name: 'agent-b (Agent)' }))
    await user.click(within(dialog).getByRole('button', { name: '添加' }))
    expect(api.post).toHaveBeenCalledWith('/projects/p1/members', {
      user_id: 'u5',
      role: 'viewer',
    })
  })

  it('owner 重命名项目:提交调用 PATCH,名称更新', async () => {
    const user = (await import('@testing-library/user-event')).default
    vi.mocked(api.patch).mockResolvedValue({ ok: true })
    renderLayout()
    await user.click(await screen.findByRole('button', { name: /重命名/ }))
    const dialog = await screen.findByRole('dialog')
    const input = within(dialog).getByLabelText('项目名')
    await user.clear(input)
    await user.type(input, '改版项目')
    await user.click(within(dialog).getByRole('button', { name: '保存' }))
    expect(api.patch).toHaveBeenCalledWith('/projects/p1', { name: '改版项目' })
  })

  it('非 owner 不显示成员管理,给出提示', async () => {
    renderLayout('viewer')
    expect(await screen.findByText(/成员授权由项目 owner 管理/)).toBeInTheDocument()
    expect(screen.queryByText('成员授权')).not.toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith('/projects/p1/members')
  })
})
