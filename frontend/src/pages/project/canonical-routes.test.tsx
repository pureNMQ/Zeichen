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
const author = '44444444-4444-4444-8444-444444444444'
const attachment = '55555555-5555-4555-8555-555555555555'
const recent = '66666666-6666-4666-8666-666666666666'
const older = '77777777-7777-4777-8777-777777777777'
const appended = '88888888-8888-4888-8888-888888888888'
const timestamp = '2026-11-17T00:00:00Z'
const projects = [
  { id: a, name: '项目 A', my_role: 'owner', created_at: timestamp },
  { id: b, name: '项目 B', my_role: 'viewer', created_at: timestamp },
]

function timelineEntry(id: string, preview: string, projectId: string = a) {
  return {
    id, project_id: projectId, requirement_id: 'REQ-1', kind: 'manual', actor_id: null,
    occurred_at: timestamp, source_task: null, reply_to: null, revised: false, withdrawn: false,
    event_type: null, event_data: null, body_preview: preview,
  }
}

let appendAttempts = 0

function respond(path: string, options?: RequestInit) {
  const url = new URL(path, 'https://app.test')
  const scopedProject = url.searchParams.get('project_id')
  const name = scopedProject === b || url.pathname.includes(b) ? 'B' : 'A'
  const projectId = name === 'B' ? b : a
  const bare = url.pathname
  if (bare === `/api/projects/${denied}`) return Response.json({ message: '项目不存在' }, { status: 404 })
  if (bare === '/api/projects') return Response.json(projects)
  if (bare === `/api/projects/${a}`) return Response.json(projects[0])
  if (bare === `/api/projects/${b}`) return Response.json(projects[1])
  if (bare === `/api/projects/${a}/completions`) {
    return Response.json({ items: [personCandidate(a), personCandidate(b)] })
  }
  if (bare === `/api/projects/${a}/people/${author}`) return Response.json(personCandidate(a))
  const timeline = `/api/projects/${projectId}/requirements/REQ-1/timeline`
  if (bare === timeline) {
    if (options?.method === 'POST') {
      appendAttempts += 1
      return appendAttempts === 1
        ? Response.json({ message: '暂时无法保存，请重试' }, { status: 503 })
        : Response.json({ entry_id: appended, version: 1, warnings: [] }, { status: 201 })
    }
    if (url.searchParams.has('cursor')) {
      return Response.json({ items: [timelineEntry(older, '较早记录', projectId)], next_cursor: null })
    }
    return Response.json({
      items: [{
        ...timelineEntry(recent, '近期回复', projectId),
        reply_to: { entry_id: older, kind: 'manual', withdrawn: false, body_preview: '较早记录', event_type: null },
      }],
      next_cursor: 'older / cursor',
    })
  }
  if (bare === `${timeline}/${older}/context`) {
    return Response.json({ anchor_id: older, items: [timelineEntry(older, '较早记录', projectId)] })
  }
  if (bare === `${timeline}/${older}`) {
    return Response.json({ ...timelineEntry(older, '', projectId), body: '较早记录的完整正文' })
  }
  if (bare === `${timeline}/${appended}/context`) {
    return Response.json({ anchor_id: appended, items: [timelineEntry(appended, '发布后的记录', projectId)] })
  }
  if (bare === `${timeline}/${appended}`) {
    return Response.json({ ...timelineEntry(appended, '', projectId), body: '发布后的完整正文' })
  }
  if (bare === `/api/v2/projects/${a}/files`) {
    return Response.json({ items: [fileCandidate(a), fileCandidate(b)], next_cursor: null })
  }
  if (bare === `/api/v2/projects/${a}/files/${attachment}`) return Response.json(fileCandidate(a))
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

function personCandidate(projectId: string) {
  return {
    id: author,
    label: projectId === a ? '橘猫' : '其他项目成员',
    kind: 'agent',
    href: `/projects/${projectId}/people/${author}`,
    detail: 'orange-cat',
  }
}

function fileCandidate(projectId: string) {
  return {
    id: attachment, project_id: projectId,
    name: projectId === a ? '橘猫.png' : '其他项目图片',
    media_type: 'image/png', size: 346,
    href: `/projects/${projectId}/files/${attachment}`,
    preview_href: `/api/v2/projects/${projectId}/files/${attachment}/content?inline=true`,
  }
}

const fetchMock = vi.fn((path: string, options?: RequestInit) => Promise.resolve(respond(path, options)))

beforeEach(() => {
  localStorage.setItem('zeichen.currentProjectId', a)
  fetchMock.mockClear()
  appendAttempts = 0
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
    expect(fetchMock).toHaveBeenCalledWith(`/api/projects/${b}/requirements/REQ-1/timeline?limit=20`, expect.anything())
    expect(fetchMock.mock.calls.some(([path]) => path.includes('/comments') || path.includes('/activity'))).toBe(false)
    expect(screen.queryByRole('textbox', { name: '时间轴正文' })).not.toBeInTheDocument()
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

  it('looks up mentions and files from the canonical Wiki editor using its project', async () => {
    const user = open(`/projects/${a}/wiki/DOC-1?mode=edit`)
    const editor = await screen.findByRole('textbox', { name: 'Markdown 正文' })
    await user.type(editor, ' @橘')
    expect(await screen.findByRole('option', { name: /橘猫 Agent/ })).toBeVisible()
    expect(screen.queryByRole('option', { name: /其他项目成员/ })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/projects/${a}/completions?mode=people&q=%E6%A9%98`, expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    await user.keyboard('{Enter}{Alt>}{Shift>}K{/Shift}{/Alt}')
    const search = screen.getByRole('combobox', { name: '查找图片' })
    await user.type(search, '橘')
    expect(await screen.findByRole('option', { name: /橘猫.png 文件/ })).toBeVisible()
    expect(screen.queryByRole('option', { name: /其他项目图片/ })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v2/projects/${a}/files?query=%E6%A9%98&limit=20&images_only=true`, expect.anything(),
    )
    await user.keyboard('{Enter}')
    expect(editor).toHaveValue(`正文 A [@橘猫](</projects/${a}/people/${author}>) ![橘猫.png](</projects/${a}/files/${attachment}>) `)
  })

  it('opens the person chosen by a canonical mention', async () => {
    open(`/projects/${a}/people/${author}`)
    expect(await screen.findByRole('heading', { name: '橘猫' })).toBeVisible()
    expect(screen.getByText('Agent · orange-cat')).toBeVisible()
  })

  it('opens file references at the stable path and separates preview from download', async () => {
    open(`/projects/${a}/files/${attachment}`)
    expect(await screen.findByRole('heading', { name: '橘猫.png' })).toBeVisible()
    const contentUrl = `/api/v2/projects/${a}/files/${attachment}/content`
    expect(screen.getByRole('img', { name: '橘猫.png' })).toHaveAttribute('src', `${contentUrl}?inline=true`)
    expect(screen.getByRole('link', { name: '下载文件' })).toHaveAttribute('href', contentUrl)
  })

  it('loads an older timeline page and jumps from a reply to its parent context', async () => {
    const user = open(`/projects/${a}/requirements/REQ-1`)
    expect(await screen.findByText('近期回复')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '加载较早记录' }))
    expect(await screen.findByText('较早记录', { exact: true })).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/projects/${a}/requirements/REQ-1/timeline?limit=20&cursor=older+%2F+cursor`, expect.anything(),
    )
    await user.click(screen.getByRole('link', { name: '回复：较早记录' }))
    expect(await screen.findByText('较早记录的完整正文')).toBeVisible()
    expect(screen.queryByText('近期回复')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回最新记录' })).toBeVisible()
    expect(document.getElementById(`timeline-${older}`)).toHaveFocus()
  })

  it('retains the reply and reuses its request id when an append is retried', async () => {
    const user = open(`/projects/${a}/requirements/REQ-1`)
    await user.click(await screen.findByRole('button', { name: '回复' }))
    const draft = screen.getByRole('textbox', { name: '时间轴正文' })
    expect(draft).toHaveFocus()
    await user.keyboard('重试仍保留的正文')
    await user.click(screen.getByRole('button', { name: '发布回复' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法保存，请重试')
    expect(draft).toHaveValue('重试仍保留的正文')
    await user.click(screen.getByRole('button', { name: '发布回复' }))
    expect(await screen.findByText('发布后的完整正文')).toBeVisible()
    expect(draft).toHaveValue('')
    const posts = fetchMock.mock.calls.filter(([path, options]) => path.endsWith('/timeline') && options?.method === 'POST')
    expect(posts).toHaveLength(2)
    const payloads = posts.map(([, options]) => JSON.parse(String(options?.body)))
    expect(payloads[0]).toEqual({ body: '重试仍保留的正文', reply_to: recent, request_id: expect.any(String) })
    expect(payloads[1]).toEqual(payloads[0])
  })
})
