import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MembersPage } from '@/pages/members'
import { NotificationProvider } from '@/components/ui/notification'

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

import { ApiError, api, type MemberRow } from '@/lib/api'

const rows: MemberRow[] = [
  { id: 'u1', username: 'admin', role: 'admin', created_at: '2026-08-01T00:00:00Z', is_bootstrap: true, is_self: true, has_password: true },
  { id: 'u2', username: 'bob', role: 'member', created_at: '2026-08-02T00:00:00Z', is_bootstrap: false, is_self: false, has_password: false },
]

function renderMembers() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <NotificationProvider>
        <MembersPage />
      </NotificationProvider>
    </QueryClientProvider>,
  )
}

describe('MembersPage 成员列表渲染', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('以响应式卡片渲染成员与角色', async () => {
    vi.mocked(api.get).mockResolvedValue(rows)
    renderMembers()

    expect(await screen.findByText('admin')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(screen.getAllByTestId('member-card')).toHaveLength(rows.length)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getAllByText('成员').length).toBeGreaterThan(0)
    expect(screen.getAllByText('管理员').length).toBeGreaterThan(0)
    expect(screen.queryByText('不能修改自己的角色')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /重新生成 admin 的设密链接/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重新生成 bob 的设密链接/ })).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/members')
  })

  it('空列表展示占位', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    renderMembers()

    expect(await screen.findByText('暂无成员')).toBeInTheDocument()
  })

  it('创建成员后仅在弹窗展示可复制的设密链接', async () => {
    vi.mocked(api.get).mockResolvedValue(rows)
    vi.mocked(api.post).mockResolvedValue({
      ...rows[1],
      password_setup_url: 'http://localhost:5173/set-password?token=one-time-token',
    })
    renderMembers()
    const user = (await import('@testing-library/user-event')).default

    await user.click(await screen.findByRole('button', { name: '添加成员' }))
    await user.type(screen.getByLabelText('登录账号'), 'carol')
    await user.click(screen.getByRole('button', { name: '添加' }))

    expect(api.post).toHaveBeenCalledWith('/members', { username: 'carol', role: 'member' })
    expect(await screen.findByLabelText('设密链接')).toHaveValue(
      'http://localhost:5173/set-password?token=one-time-token',
    )
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument()
  })

  it('成员操作失败时以非模态提示展示错误', async () => {
    vi.mocked(api.get).mockResolvedValue(rows)
    vi.mocked(api.post).mockRejectedValue(new ApiError(409, '成员已完成设密，不能重新生成设密链接'))
    renderMembers()
    const user = (await import('@testing-library/user-event')).default

    await user.click(await screen.findByRole('button', { name: /重新生成 bob 的设密链接/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('成员已完成设密，不能重新生成设密链接')
  })
})
