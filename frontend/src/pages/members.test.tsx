import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MembersPage } from '@/pages/members'

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

import { api, type MemberRow } from '@/lib/api'

const rows: MemberRow[] = [
  { id: 'u1', username: 'admin', role: 'admin', created_at: '2026-08-01T00:00:00Z' },
  { id: 'u2', username: 'bob', role: 'member', created_at: '2026-08-02T00:00:00Z' },
]

function renderMembers() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MembersPage />
    </QueryClientProvider>,
  )
}

describe('MembersPage 成员列表渲染', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染成员行与角色', async () => {
    vi.mocked(api.get).mockResolvedValue(rows)
    renderMembers()

    expect(await screen.findByText('admin')).toBeInTheDocument()
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(screen.getAllByText('成员').length).toBeGreaterThan(0)
    expect(screen.getAllByText('管理员').length).toBeGreaterThan(0)
    expect(api.get).toHaveBeenCalledWith('/members')
  })

  it('空列表展示占位', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    renderMembers()

    expect(await screen.findByText('暂无成员')).toBeInTheDocument()
  })
})
