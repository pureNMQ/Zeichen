import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { ProjectSearchPage } from '@/pages/project/search-v2'
import { NotificationProvider } from '@/components/ui/notification'

vi.mock('@/lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/api')>(), api: { get: vi.fn() },
}))
vi.mock('@/lib/current-project', () => ({
  useCurrentProject: () => ({ projects: [{ id: 'a', name: '项目 A' }, { id: 'b', name: '项目 B' }] }),
}))

describe('项目搜索', () => {
  it('请求失败后可重试，成功但没有命中时才显示空态', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('搜索暂时不可用'))
      .mockResolvedValueOnce({ domains: {} })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <NotificationProvider><MemoryRouter initialEntries={['/projects/a/search?q=fixture']}>
          <Routes><Route path="/projects/:projectId/search" element={<ProjectSearchPage />} /></Routes>
        </MemoryRouter></NotificationProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('搜索暂时不可用')
    expect(screen.queryByText('没有匹配结果。')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('没有匹配结果。')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

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
    expect(screen.getByRole('checkbox', { name: '项目 B' })).not.toBeChecked()
  })

  it('搜索所选项目并在加载更多时保留筛选条件', async () => {
    vi.mocked(api.get).mockImplementation((url) => Promise.resolve({ domains: { requirement: {
      items: [{
        id: 'REQ-1', project_id: url.includes('cursor=next') ? 'b' : 'a',
        title: url.includes('cursor=next') ? '项目 B 的需求' : '当前项目的需求',
        href: url.includes('cursor=next') ? '/projects/b/requirements/REQ-1' : '/projects/a/requirements/REQ-1',
      }],
      next_cursor: url.includes('cursor=next') ? null : 'next',
    } } }))
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/projects/a/search']}>
          <Routes><Route path="/projects/:projectId/search" element={<ProjectSearchPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await userEvent.click(screen.getByRole('checkbox', { name: '项目 B' }))
    await userEvent.click(screen.getByText('高级筛选'))
    await userEvent.selectOptions(screen.getByLabelText('需求状态'), 'done')
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))
    const region = await screen.findByRole('region', { name: '需求' })
    expect(within(region).getByText('项目 A')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/v2/projects/a/search?include_project=b&requirement_status=done&limit=20')
    await userEvent.click(within(region).getByRole('button', { name: '加载更多需求' }))
    expect(await within(region).findByRole('link', { name: '项目 B 的需求' })).toHaveAttribute('href', '/projects/b/requirements/REQ-1')
    expect(within(region).getByText('项目 B')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/v2/projects/a/search?include_project=b&requirement_status=done&limit=20&domain=requirement&cursor=next')
  })
})
