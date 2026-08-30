import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

import { api } from '@/lib/api'
import { NotificationProvider } from '@/components/ui/notification'
import { SearchPage } from '@/pages/search'

// REQ-4 要点 2(前端):全局搜索页按域过滤(域 tab)+「加载更多」分页。
// 现有实现无域 tab、无分页,以下用例红灯。

function renderSearch(entry = '/search?q=登录') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <NotificationProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/search" element={<SearchPage />} />
          </Routes>
        </MemoryRouter>
      </NotificationProvider>
    </QueryClientProvider>,
  )
}

function item(id: string, title: string, domain: string, status?: string) {
  return { domain, id, project_id: 'p1', project_name: 'demo', title, summary: '摘要', status }
}

function mockAllDomains() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path.includes('domain=requirement')) return Promise.resolve({ items: [item('r1', '登录功能', 'requirement', 'in_progress')], next_cursor: null })
    const items = [
      item('r1', '登录功能', 'requirement', 'in_progress'),
      item('t1', '实现登录', 'task', 'backlog'),
      item('d1', '登录设计文档', 'document'),
      item('m1', '记忆', 'memory'),
    ]
    return Promise.resolve({ items, next_cursor: null })
  })
}

function mockPaged() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path.includes('cursor=')) return Promise.resolve({ items: [item('r2', '第二页需求', 'requirement', 'backlog')], next_cursor: null })
    return Promise.resolve({ items: [item('r1', '第一页需求', 'requirement', 'in_progress')], next_cursor: 'cursor-1' })
  })
}

describe('全局搜索页域过滤', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('提供全部/需求/任务/文档/记忆域 tab', async () => {
    mockAllDomains()
    renderSearch()

    expect(await screen.findByRole('tab', { name: '全部' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '需求' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '任务' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '文档' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '记忆' })).toBeInTheDocument()
  })

  it('点击域 tab 只请求并展示该域结果,点全部恢复跨域', async () => {
    const user = userEvent.setup()
    mockAllDomains()
    renderSearch()
    expect(await screen.findByRole('link', { name: /实现登录/ })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '需求' }))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('domain=requirement')))
    expect(await screen.findByRole('link', { name: /登录功能/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /实现登录/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /登录设计文档/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /记忆/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '全部' }))
    await waitFor(() => {
      const last = vi.mocked(api.get).mock.calls.at(-1)?.[0] ?? ''
      expect(last).not.toContain('domain=')
    })
    expect(await screen.findByRole('link', { name: /实现登录/ })).toBeInTheDocument()
  })
})

describe('全局搜索页加载更多', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('首页带 next_cursor 时显示加载更多,点击追加下一页并在末页隐藏', async () => {
    const user = userEvent.setup()
    mockPaged()
    renderSearch()

    expect(await screen.findByRole('link', { name: /第一页需求/ })).toBeInTheDocument()
    const more = screen.getByRole('button', { name: '加载更多' })
    await user.click(more)

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('cursor=')))
    expect(await screen.findByRole('link', { name: /第二页需求/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /第一页需求/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '加载更多' })).not.toBeInTheDocument()
  })
})
