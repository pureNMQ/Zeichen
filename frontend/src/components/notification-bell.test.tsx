import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() } }
})

import { api } from '@/lib/api'
import { NotificationBell } from '@/components/notification-bell'

const items = [
  { id: 'n1', target_type: 'task', target_id: 't1', action: 'status', summary: 'backlog → in_progress', actor_id: 'a1', read: false, created_at: '2026-08-01T00:00:00Z' },
  { id: 'n2', target_type: 'requirement', target_id: 'r1', action: 'comment', summary: '添加评论', actor_id: 'a1', read: true, created_at: '2026-08-01T01:00:00Z' },
]

function renderBell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function mockBell() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/notifications/unread-count') return Promise.resolve({ count: 1 })
    if (path.startsWith('/notifications')) return Promise.resolve({ items })
    return Promise.resolve({})
  })
}

describe('通知铃铛', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('显示未读数角标', async () => {
    mockBell()
    renderBell()
    const badge = await screen.findByText('1')
    expect(badge).toBeInTheDocument()
  })

  it('展开列出通知，点击跳转对应实体并标记已读', async () => {
    mockBell()
    const user = userEvent.setup()
    renderBell()

    await user.click(await screen.findByRole('button', { name: '通知' }))
    expect(await screen.findByText(/backlog → in_progress/)).toBeInTheDocument()
    expect(screen.getByText(/添加评论/)).toBeInTheDocument()

    const target = screen.getByText(/backlog → in_progress/)
    await user.click(target)
    expect(api.post).toHaveBeenCalledWith('/notifications/n1/read')
  })

  it('一键已读调用 read-all', async () => {
    mockBell()
    const user = userEvent.setup()
    renderBell()

    await user.click(await screen.findByRole('button', { name: '通知' }))
    const markAll = await screen.findByRole('button', { name: '一键已读' })
    await user.click(markAll)
    expect(api.post).toHaveBeenCalledWith('/notifications/read-all')
  })
})
