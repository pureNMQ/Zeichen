import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
import { CurrentProjectProvider } from '@/lib/current-project'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { DocumentWorkbenchPage } from '@/pages/documents'

// REQ-4 要点 3:启用文档树内搜索。现有实现是禁用占位输入框,以下用例红灯;
// 实现后「搜索文档」输入框启用(保留 autoComplete=off),按标题客户端过滤当前树。
const nodes = [
  { id: 'parent', node_kind: 'document' as const, title: '部署 Runbook', doc_type: 'wiki' as const, content: '', metadata: {}, project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', deleted_at: null, parent_id: null, directory_id: null, has_children: false },
  { id: 'other', node_kind: 'document' as const, title: '另一篇 Wiki', doc_type: 'wiki' as const, content: '', metadata: {}, project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', deleted_at: null, parent_id: null, directory_id: null, has_children: false },
]

function renderWorkbench(entry = '/documents/wiki') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CurrentProjectProvider>
        <DocumentNavigationProvider>
          <MemoryRouter initialEntries={[entry]}>
            <Routes>
              <Route path="/documents/wiki" element={<DocumentWorkbenchPage module="wiki" />} />
              <Route path="/documents/wiki/:id" element={<DocumentWorkbenchPage module="wiki" />} />
            </Routes>
          </MemoryRouter>
        </DocumentNavigationProvider>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('文档树内搜索', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve([{ id: 'p1', name: '测试项目', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' }])
      if (path === '/projects/p1/documents/wiki/children?limit=100') return Promise.resolve({ items: nodes, next_cursor: null })
      if (path === '/projects/p1/documents/index') return Promise.resolve({ project_id: 'p1', total: 0, sections: [], lint: { missing_kind: [], missing_summary: [], broken_links: [] } })
      return Promise.resolve({ items: [], next_cursor: null })
    })
  })

  it('搜索框启用、声明 autoComplete=off,并按标题过滤文档树(大小写不敏感)', async () => {
    const user = userEvent.setup()
    renderWorkbench()

    const search = await screen.findByRole('textbox', { name: /搜索文档/ })
    expect(search).not.toBeDisabled()
    expect(search).toHaveAttribute('autocomplete', 'off')

    await user.type(search, 'runbook')
    expect(screen.getByRole('button', { name: '部署 Runbook' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '另一篇 Wiki' })).not.toBeInTheDocument()
  })

  it('清空搜索词后恢复完整文档树', async () => {
    const user = userEvent.setup()
    renderWorkbench()

    const search = await screen.findByRole('textbox', { name: /搜索文档/ })
    await user.type(search, 'runbook')
    expect(screen.queryByRole('button', { name: '另一篇 Wiki' })).not.toBeInTheDocument()

    await user.clear(search)
    expect(screen.getByRole('button', { name: '部署 Runbook' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '另一篇 Wiki' })).toBeInTheDocument()
  })

  it('无匹配时文档树为空且不报错', async () => {
    const user = userEvent.setup()
    renderWorkbench()

    const search = await screen.findByRole('textbox', { name: /搜索文档/ })
    await user.type(search, '不存在的标题')
    expect(screen.queryByRole('button', { name: '部署 Runbook' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '另一篇 Wiki' })).not.toBeInTheDocument()
  })
})
