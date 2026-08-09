import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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

function mockSearch() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path.startsWith('/search')) {
      return Promise.resolve({
        items: [
          { domain: 'requirement', id: 'r1', project_id: 'p1', project_name: 'demo', title: '登录功能', summary: '登录页面设计', status: 'in_progress' },
          { domain: 'task', id: 't1', project_id: 'p1', project_name: 'demo', title: '实现登录', summary: '校验逻辑', status: 'backlog' },
          { domain: 'document', id: 'd1', project_id: 'p1', project_name: 'demo', title: '登录设计文档', summary: '说明', doc_type: 'wiki' },
          { domain: 'code_symbol', id: 'c1', project_id: 'p1', project_name: 'demo', title: 'LoginService', summary: 'handles login', kind: 'class' },
          { domain: 'memory', id: 'm1', project_id: 'p1', project_name: 'demo', title: '记忆', summary: '历史记忆片段' },
        ],
      })
    }
    return Promise.resolve({})
  })
}

describe('全局搜索页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('按域分组渲染搜索结果，并带跳转链接', async () => {
    mockSearch()
    renderSearch()

    expect(await screen.findByRole('heading', { name: /需求/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /任务/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /文档/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /代码符号/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /记忆/ })).toBeInTheDocument()

    expect(screen.getByRole('link', { name: /登录功能/ })).toHaveAttribute('href', '/requirements/r1')
    expect(screen.getByRole('link', { name: /实现登录/ })).toHaveAttribute('href', '/tasks/t1')
    expect(screen.getByRole('link', { name: /登录设计文档/ })).toHaveAttribute('href', '/documents/wiki/d1')
    expect(screen.getByRole('link', { name: /LoginService/ })).toHaveAttribute('href', '/code-reference/c1')

    expect(screen.getAllByText('demo').length).toBeGreaterThan(0)
  })

  it('无结果时显示空状态', async () => {
    vi.mocked(api.get).mockImplementation((path: string) =>
      path.startsWith('/search') ? Promise.resolve({ items: [] }) : Promise.resolve({}),
    )
    renderSearch('/search?q=不存在')
    expect(await screen.findByText(/没有找到/)).toBeInTheDocument()
  })
})
