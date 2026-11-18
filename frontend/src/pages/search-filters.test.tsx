import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { api } from '@/lib/api'
import { SearchPage } from './search'
import { ProjectSearchPage } from './project/search-v2'

vi.mock('@/lib/api', async (original) => ({
  ...await original<typeof import('@/lib/api')>(), api: { get: vi.fn() },
}))
vi.mock('@/lib/current-project', () => ({ useCurrentProject: () => ({ projects: [{ id: 'p1', name: '测试' }] }) }))

describe('旧文档搜索筛选', () => {
  it('书签保留文档类型，显示 v2 Wiki，可以分页或切回全部结果', async () => {
    vi.mocked(api.get).mockImplementation(async (path) => {
      if (!path.startsWith('/v2/projects/p1/search?')) throw Error('unexpected ' + path)
      if (path.includes('cursor=wiki-2')) return { domains: { wiki: { items: [
        { project_id: 'p1', id: 'DOC-2', title: '第二篇 Wiki', href: '/projects/p1/wiki/DOC-2' },
      ], next_cursor: null } } }
      return { domains: {
        requirement: { items: [{ project_id: 'p1', id: 'REQ-1', title: '一项需求', href: '/projects/p1/requirements/REQ-1' }], next_cursor: null },
        wiki: { items: [{ project_id: 'p1', id: 'DOC-1', title: '第一篇 Wiki', href: '/projects/p1/wiki/DOC-1' }], next_cursor: 'wiki-2' },
      } }
    })
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/search?project_id=p1&q=登录&domain=document']}><Routes>
        <Route path="/search" element={<SearchPage />} />
        <Route path="/projects/:projectId/search" element={<ProjectSearchPage />} />
      </Routes></MemoryRouter>
    </QueryClientProvider>)
    expect(await screen.findByRole('link', { name: '第一篇 Wiki' })).toHaveAttribute('href', '/projects/p1/wiki/DOC-1')
    expect(screen.queryByText('一项需求')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '加载更多Wiki' }))
    expect(await screen.findByRole('link', { name: '第二篇 Wiki' })).toHaveAttribute('href', '/projects/p1/wiki/DOC-2')
    expect(screen.queryByRole('button', { name: '加载更多Wiki' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '全部' }))
    expect(await screen.findByRole('link', { name: '一项需求' })).toHaveAttribute('href', '/projects/p1/requirements/REQ-1')
  })
})
