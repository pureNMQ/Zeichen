import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { NotificationProvider } from '@/components/ui/notification'
import { api } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { SearchPage } from './search'
import { CanonicalProjectRoute } from './project/canonical-routes'
import { ProjectSearchPage } from './project/search-v2'

vi.mock('@/lib/api', async (original) => ({
  ...await original<typeof import('@/lib/api')>(), api: { get: vi.fn() },
}))

const projects = [{ id: 'a', name: '设计组' }, { id: 'b', name: '开发组' }]

function show(entry: string, accessible = projects) {
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === '/projects') return accessible
    const project = accessible.find((p) => path === '/projects/' + p.id)
    if (project) return project
    if (path.startsWith('/v2/projects/b/search?')) return { domains: { wiki: { items: [{
      id: 'DOC-1', project_id: 'b', title: '开发组的新 Wiki', href: '/projects/b/wiki/DOC-1',
    }], next_cursor: null } } }
    throw Error('项目不存在或无访问权限')
  })
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <NotificationProvider><MemoryRouter initialEntries={[entry]}><CurrentProjectProvider>
      <Routes>
        <Route path="/search" element={<SearchPage />} />
        <Route path="/projects/:projectId" element={<CanonicalProjectRoute />}>
          <Route path="search" element={<ProjectSearchPage />} />
        </Route>
      </Routes>
    </CurrentProjectProvider></MemoryRouter></NotificationProvider>
  </QueryClientProvider>)
}

describe('旧搜索书签', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear() })

  it('保留查询，在用户选定项目前不搜索，也不默认扩大查询范围', async () => {
    localStorage.setItem('zeichen.currentProjectId', 'a')
    show('/search?q=C%2B%2B&include_project=a#results')
    const project = await screen.findByRole('link', { name: '开发组' })
    expect(project).toHaveAttribute('href', '/projects/b/search?q=C%2B%2B#results')
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/search?'))
    await userEvent.click(project)
    expect(await screen.findByRole('link', { name: '开发组的新 Wiki' })).toHaveAttribute('href', '/projects/b/wiki/DOC-1')
    expect(screen.getByRole('searchbox')).toHaveValue('C++')
    expect(api.get).toHaveBeenCalledWith('/v2/projects/b/search?q=C%2B%2B&limit=20')
    expect(api.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/search/))
  })

  it('书签指定项目时进入对应项目，即使当前选择不同', async () => {
    localStorage.setItem('zeichen.currentProjectId', 'a')
    show('/search?project_id=b&q=Wiki')
    expect(await screen.findByRole('link', { name: '开发组的新 Wiki' })).toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/v2/projects/a/search'))
  })

  it('只有一个可访问项目时直接搜索', async () => {
    show('/search?q=Wiki', [projects[1]])
    expect(await screen.findByRole('link', { name: '开发组的新 Wiki' })).toBeInTheDocument()
  })

  it('指定未获授权项目时不回退到其他项目，也不发出内容查询', async () => {
    show('/search?project_id=unknown&q=Wiki')
    expect(await screen.findByRole('alert')).toHaveTextContent('项目不存在或无访问权限')
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/search?'))
  })

  it('没有获准项目时显示空态', async () => {
    show('/search?q=Wiki', [])
    expect(await screen.findByText('暂无可搜索的项目。')).toBeInTheDocument()
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/search?'))
  })
})
