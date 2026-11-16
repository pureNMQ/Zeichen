import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Outlet } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from '@/App'
import { NotificationProvider } from '@/components/ui/notification'

vi.mock('@/components/app-shell', () => ({ AppShell: () => <Outlet /> }))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { id: 'me', username: 'me', workspace_role: 'member' }, loading: false }),
}))
vi.mock('@/components/vditor-ir-editor', () => ({
  VditorIrEditor: () => null,
  VditorMarkdownViewer: ({ markdown }: { markdown: string }) => <p>{markdown}</p>,
}))

const a = '11111111-1111-4111-8111-111111111111'
const b = '22222222-2222-4222-8222-222222222222'
const denied = '33333333-3333-4333-8333-333333333333'
const timestamp = '2026-11-17T00:00:00Z'
const projects = [
  { id: a, name: '项目 A', my_role: 'owner', created_at: timestamp },
  { id: b, name: '项目 B', my_role: 'viewer', created_at: timestamp },
]

function respond(path: string) {
  const url = new URL(path, 'https://app.test')
  const scopedProject = url.searchParams.get('project_id')
  const name = scopedProject === b || url.pathname.includes(b) ? 'B' : 'A'
  const projectId = name === 'B' ? b : a
  const bare = url.pathname
  if (bare === `/api/projects/${denied}`) return Response.json({ message: '项目不存在' }, { status: 404 })
  if (bare === '/api/projects') return Response.json(projects)
  if (bare === `/api/projects/${a}`) return Response.json(projects[0])
  if (bare === `/api/projects/${b}`) return Response.json(projects[1])
  if (bare === `/api/projects/${projectId}/requirements/REQ-1` || bare === '/api/requirements/REQ-1') {
    return Response.json({ id: 'REQ-1', project_id: projectId, title: `同码需求 ${name}`, status: 'backlog' })
  }
  if (bare === '/api/tasks/TASK-101') {
    return Response.json({
      id: 'TASK-101', project_id: projectId, requirement_id: 'REQ-1',
      title: `独立读取任务 ${name}`, status: 'backlog',
    })
  }
  if (bare === '/api/documents/wiki/DOC-1') {
    return Response.json({
      id: 'DOC-1', project_id: projectId, title: `同码 Wiki ${name}`,
      content: `正文 ${name}`, metadata: {}, created_at: timestamp, updated_at: timestamp,
    })
  }
  return Response.json({ items: [] })
}

const fetchMock = vi.fn((path: string) => Promise.resolve(respond(path)))

beforeEach(() => {
  localStorage.setItem('zeichen.currentProjectId', a)
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function open(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <NotificationProvider>
        <MemoryRouter initialEntries={[path]}>
          <Link to={`/projects/${a}/requirements/REQ-1`}>打开 A 同码需求</Link>
          <Link to={`/projects/${a}/wiki/DOC-1`}>打开 A 同码 Wiki</Link>
          <App />
        </MemoryRouter>
      </NotificationProvider>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('canonical project routes', () => {
  it('keeps the project scope in requirement details, panels and navigation', async () => {
    const user = open(`/projects/${b}/requirements/REQ-1`)
    expect(await screen.findByRole('heading', { name: /同码需求 B/ })).toBeVisible()
    expect(screen.getByRole('link', { name: '← 返回需求' })).toHaveAttribute('href', `/projects/${b}/requirements`)
    expect(screen.queryByRole('button', { name: '新建任务' })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`/api/targets/requirement/REQ-1/comments?limit=50&project_id=${b}`, expect.anything())
    expect(fetchMock).toHaveBeenCalledWith(`/api/targets/requirement/REQ-1/attachments?project_id=${b}`, expect.anything())
    expect(localStorage.getItem('zeichen.currentProjectId')).toBe(a)
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/requirements/REQ-1')).toBe(false)

    await user.click(screen.getByRole('link', { name: '打开 A 同码需求' }))
    expect(await screen.findByRole('heading', { name: /同码需求 A/ })).toBeVisible()
    expect(screen.getByRole('button', { name: '新建任务' })).toBeVisible()
  })

  it('opens a task directly even when the requirement task page omits it', async () => {
    open(`/projects/${b}/tasks/TASK-101`)
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('独立读取任务 B')).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(`/api/tasks/TASK-101?project_id=${b}`, expect.anything())
    expect(fetchMock.mock.calls.some(([path]) => path === '/api/tasks/TASK-101')).toBe(false)
  })

  it('loads the exact Wiki even when the selected project has the same short code', async () => {
    const user = open(`/projects/${b}/wiki/DOC-1`)
    expect(await screen.findByRole('heading', { name: '同码 Wiki B' })).toBeVisible()
    expect(screen.getByText('正文 B')).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(`/api/documents/wiki/DOC-1/references?project_id=${b}`, expect.anything())
    await user.click(screen.getByRole('link', { name: '打开 A 同码 Wiki' }))
    expect(await screen.findByRole('heading', { name: '同码 Wiki A' })).toBeVisible()
    expect(screen.getByText('正文 A')).toBeVisible()
  })

  it('stops at a denied route project without falling back to the selected project', async () => {
    open(`/projects/${denied}/wiki/DOC-1`)
    expect(await screen.findByRole('alert')).toHaveTextContent('项目不存在')
    expect(fetchMock.mock.calls.some(([path]) => path.includes('DOC-1'))).toBe(false)
  })

  it('continues resolving legacy requirement links', async () => {
    open('/requirements/REQ-1')
    expect(await screen.findByRole('heading', { name: /同码需求 A/ })).toBeVisible()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/requirements/REQ-1', expect.anything()))
  })
})
