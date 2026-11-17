import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { ProjectSearchPage } from '@/pages/project/search-v2'

vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }))
vi.mock('@/lib/current-project', () => ({
  useCurrentProject: () => ({ projects: [{ id: 'a', name: '项目 A' }, { id: 'b', name: '项目 B' }] }),
}))

describe('项目搜索', () => {
  it('按当前项目聚合，只续读选择的结果域', async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url.includes('cursor=wiki-page')) {
        return Promise.resolve({ domains: { wiki: {
          items: [{ id: 'DOC-2', title: '第二篇 Wiki', href: '/projects/a/wiki/DOC-2' }], next_cursor: null,
        } } })
      }
      return Promise.resolve({ domains: {
        timeline: { items: [{ id: 'entry-1', title: '测试记录', href: '/projects/a/requirements/REQ-1#timeline-entry-1' }], next_cursor: null },
        wiki: { items: [{ id: 'DOC-1', title: '第一篇 Wiki', href: '/projects/a/wiki/DOC-1' }], next_cursor: 'wiki-page' },
      } })
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/projects/a/search?q=fixture']}>
          <Routes><Route path="/projects/:projectId/search" element={<ProjectSearchPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('link', { name: '测试记录' })).toHaveAttribute('href', '/projects/a/requirements/REQ-1#timeline-entry-1')
    expect(api.get).toHaveBeenCalledWith('/v2/projects/a/search?q=fixture&limit=20')
    const wiki = screen.getByRole('region', { name: 'Wiki' })
    await userEvent.click(within(wiki).getByRole('button', { name: '加载更多Wiki' }))
    expect(await within(wiki).findByText('第二篇 Wiki')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/v2/projects/a/search?q=fixture&limit=20&domain=wiki&cursor=wiki-page')
    expect(screen.getByRole('link', { name: '在项目 B中搜索' })).toHaveAttribute('href', '/projects/b/search?q=fixture')
  })
})
