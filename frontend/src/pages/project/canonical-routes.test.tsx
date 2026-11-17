import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
let wikiParent: string | null = null
let deleteAttempts = 0
let wikiDeleted = false
let fileRestored = false
let fileName = '橘猫.png'
let fileDeleted = false

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
  if (bare === `${timeline}/${older}/revisions/1`) {
    return Response.json({ version: 1, kind: 'create', body: '引用文件时的原始正文', reason: null, created_at: timestamp })
  }
  if (bare === `${timeline}/${appended}/context`) {
    return Response.json({ anchor_id: appended, items: [timelineEntry(appended, '发布后的记录', projectId)] })
  }
  if (bare === `${timeline}/${appended}`) {
    return Response.json({ ...timelineEntry(appended, '', projectId), body: '发布后的完整正文' })
  }
  if (bare === `/api/v2/projects/${a}/files`) {
    const items = [fileCandidate(a), fileCandidate(b)]
    if (url.searchParams.get('state') === 'deleted') {
      return Response.json({ items: fileRestored ? [] : items, next_cursor: null })
    }
    return Response.json({ items: fileDeleted ? [] : items, next_cursor: url.searchParams.has('cursor') ? null : 'file / more' })
  }
  if (bare === `/api/v2/projects/${a}/files/limits`) {
    return Response.json({ max_file_bytes: 4096, project_quota_bytes: 32768 })
  }
  if (bare === `/api/v2/projects/${projectId}/files/associations`) {
    return Response.json({ items: [], next_cursor: null })
  }
  if (bare === `/api/v2/projects/${a}/files/${attachment}`) {
    if (options?.method === 'PATCH') fileName = JSON.parse(String(options.body)).name
    if (options?.method === 'DELETE') {
      fileDeleted = true
      return Response.json({ id: attachment, project_id: a, deleted: true })
    }
    return Response.json(fileCandidate(a))
  }
  if (bare === `/api/v2/projects/${a}/files/${attachment}/trash`) {
    return Response.json({
      ...fileCandidate(a), preview_href: null, download_href: null,
      deleted_at: timestamp, deleted_by: '77777777-7777-4777-8777-777777777777',
    })
  }
  if (bare === `/api/v2/projects/${a}/files/${attachment}/usage`) {
    const history = url.searchParams.get('include_history') === 'true'
      ? [
        { href: `/projects/${a}/wiki/DOC-1?version=2`, label: '设计手册 · v2', kind: 'wiki', current: false },
        { href: `/projects/${a}/requirements/REQ-1?timelineVersion=1#timeline-${older}`,
          label: '需求时间轴 · v1', kind: 'timeline', current: false },
      ]
      : []
    return Response.json({
      items: [{ href: `/projects/${a}/wiki/DOC-1`, label: '设计手册', kind: 'wiki', current: true }, ...history,
        { href: `/projects/${b}/wiki/DOC-1`, label: '其他项目引用', kind: 'wiki', current: true }],
      next_cursor: null,
    })
  }
  if (bare === `/api/v2/projects/${a}/files/${attachment}/restore`) {
    fileRestored = true
    fileDeleted = false
    return Response.json(fileCandidate(a))
  }
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
      id: 'DOC-1', project_id: projectId, title: `旧版 Wiki ${name}`,
      content: `旧版正文 ${name}`, metadata: {}, created_at: timestamp, updated_at: timestamp,
    })
  }
  const v2Wiki = `/api/v2/projects/${projectId}/wiki`
  const v2Document = {
    id: 'DOC-1', project_id: projectId, title: `同码 Wiki ${name}`,
    parent_id: wikiParent, version: 4, body: `正文 ${name}`, summary: '迁移摘要', category: '研究', tags: ['测量，质检'],
  }
  const v2Detail = `${v2Wiki}/DOC-1`
  const v2Trash = `${v2Wiki}/trash`
  const deletedDocument = { ...v2Document, deleted_at: timestamp }
  if (bare === `${v2Wiki}/DOC-1`) {
    if (options?.method === 'PATCH') return Response.json({ message: '当前 Wiki 版本已变化' }, { status: 409 })
    if (options?.method === 'DELETE') {
      deleteAttempts += 1
      if (deleteAttempts === 1) return Response.json({ message: 'Wiki 删除范围已变化，请重新确认' }, { status: 409 })
      wikiDeleted = true
      return Response.json({ id: v2Document.id, project_id: projectId, version: 4, deleted: true })
    }
    if (wikiDeleted) return Response.json({ message: 'Wiki 不存在' }, { status: 404 })
    return Response.json(v2Document)
  }
  if (bare === `${v2Detail}/delete-impact`) {
    return Response.json({ ...v2Document, affected_count: deleteAttempts ? 3 : 2, sample: ['DOC-1', 'DOC-3'] })
  }
  if (bare === `${v2Detail}/location`) {
    wikiParent = JSON.parse(String(options?.body)).parent_id
    return Response.json({ id: v2Document.id, project_id: projectId, version: 5 })
  }
  if (bare === `${v2Detail}/versions`) {
    return url.searchParams.has('before')
      ? Response.json({ items: [{ version: 2, title: '旧标题', created_at: timestamp }], next_before: null })
      : Response.json({ items: [{ version: 4, title: '新标题', created_at: timestamp }], next_before: 4 })
  }
  if (bare === `${v2Detail}/versions/2`) return Response.json({ ...v2Document, version: 2, body: '第 2 版正文' })
  if (bare === `${v2Detail}/versions/2/restore`) return Response.json({ id: v2Document.id, project_id: projectId, version: 5 })
  if (bare === v2Trash) return Response.json({ items: wikiDeleted ? [deletedDocument] : [], next_cursor: null })
  if (bare === `${v2Trash}/DOC-1`) return Response.json(deletedDocument)
  if (bare === `${v2Trash}/DOC-1/restore`) {
    wikiDeleted = false
    return Response.json({ id: v2Document.id, project_id: projectId, version: 4 })
  }
  if (bare === `${v2Wiki}/TERM-8`) {
    return Response.json({ ...v2Document, id: 'TERM-8', title: '迁移词条' })
  }
  if (bare === `${v2Wiki}/DOC-404`) return Response.json({ message: 'Wiki 不存在' }, { status: 404 })
  if (bare === v2Wiki) {
    if (options?.method === 'POST') return Response.json({ id: 'DOC-1', project_id: projectId, version: 1 }, { status: 201 })
    return Response.json({ items: [
      ...(wikiDeleted ? [] : [v2Document]),
      { ...v2Document, id: 'DOC-2', parent_id: null, title: '新上级 Wiki' },
      ...(wikiDeleted ? [] : [{ ...v2Document, id: 'DOC-3', parent_id: 'DOC-1', title: '自身子 Wiki' }]),
    ], next_cursor: null })
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
    name: projectId === a ? fileName : '其他项目图片',
    media_type: 'image/png', size: 346,
    href: `/projects/${projectId}/files/${attachment}`,
    preview_href: `/api/v2/projects/${projectId}/files/${attachment}/content?inline=true`,
  }
}

const fetchMock = vi.fn((path: string, options?: RequestInit) => Promise.resolve(respond(path, options)))
type UploadAttempt = { url: string; body: File; finish: (status: number) => void }

function mockUploadRequests() {
  const attempts: UploadAttempt[] = []
  vi.stubGlobal('XMLHttpRequest', class extends EventTarget {
    upload = new EventTarget()
    status = 0
    response: unknown
    url = ''

    open(_method: string, url: string) { this.url = url }

    send(file: File) {
      attempts.push({
        url: this.url,
        body: file,
        finish: (status) => {
          this.status = status
          this.response = status === 201 ? fileCandidate(a) : { message: '请重试上传' }
          this.dispatchEvent(new Event('load'))
          this.dispatchEvent(new Event('loadend'))
        },
      })
      this.upload.dispatchEvent(new ProgressEvent('progress', { lengthComputable: true, loaded: 1, total: 2 }))
    }

    abort() {
      this.dispatchEvent(new Event('abort'))
      this.dispatchEvent(new Event('loadend'))
    }
  })
  return attempts
}

beforeEach(() => {
  localStorage.setItem('zeichen.currentProjectId', a)
  fetchMock.mockClear()
  appendAttempts = 0
  wikiParent = null
  deleteAttempts = 0
  wikiDeleted = false
  fileRestored = false
  fileDeleted = false
  fileName = '橘猫.png'
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
          <Link to={`/projects/${b}/wiki?mode=trash`}>打开 B 回收站</Link>
          <Link to="/documents/wiki/DOC-1">旧版 Wiki</Link>
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
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v2/projects/${b}/files/associations?target_kind=requirements&target_id=REQ-1`, expect.anything(),
    )
    expect(fetchMock.mock.calls.some(([path]) => path.includes('/attachments'))).toBe(false)
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
    expect(fetchMock).toHaveBeenCalledWith(`/api/v2/projects/${b}/wiki/DOC-1`, expect.anything())
    expect(fetchMock.mock.calls.some(([path]) => path.startsWith('/api/documents/wiki/DOC-1'))).toBe(false)
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
    expect(fetchMock).toHaveBeenCalledWith(`/api/projects/${a}/requirements/REQ-1/timeline?limit=20`, expect.anything())
    expect(fetchMock.mock.calls.some(([path]) => path.includes('/comments'))).toBe(false)
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

  it('uploads pasted file bytes to the project and reuses the request id on retry', async () => {
    const attempts = mockUploadRequests()
    const user = open(`/projects/${a}/wiki/DOC-1?mode=edit`)
    const editor = await screen.findByRole<HTMLTextAreaElement>('textbox', { name: 'Markdown 正文' })
    await user.click(editor)
    await user.keyboard(' ')
    editor.setSelectionRange(editor.value.length, editor.value.length)
    const file = new File(['image bytes'], '橘猫.png', { type: 'image/png' })
    fireEvent.paste(editor, { clipboardData: { files: [file] } })
    expect(await screen.findByRole('progressbar', { name: '上传进度' })).toHaveAttribute('value', '50')
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    expect(attempts[0].body).toBe(file)
    const attemptPath = new URL(attempts[0].url, 'https://example.invalid')
    expect(attemptPath.pathname).toBe(`/api/v2/projects/${a}/files`)
    expect(attemptPath.searchParams.get('name')).toBe(file.name)
    expect(attemptPath.searchParams.get('request_id')).toMatch(/^[a-f0-9-]{36}$/)
    await act(async () => attempts[0].finish(503))
    expect(await screen.findByRole('alert')).toHaveTextContent('请重试上传')
    expect(editor).toHaveValue('正文 A ')
    await user.click(screen.getByRole('button', { name: '重试上传' }))
    await waitFor(() => expect(attempts).toHaveLength(2))
    expect(attempts[1].url).toBe(attempts[0].url)
    await act(async () => attempts[1].finish(201))
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue(`正文 A ![橘猫.png](</projects/${a}/files/${attachment}>) `)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled()
  })

  it('opens migrated TERM references and retains the old Wiki route during transition', async () => {
    const user = open(`/projects/${a}/wiki/TERM-8`)
    expect(await screen.findByRole('heading', { name: '迁移词条' })).toBeVisible()
    await user.click(screen.getByRole('link', { name: '旧版 Wiki' }))
    expect(await screen.findByRole('heading', { name: '旧版 Wiki A' })).toBeVisible()
    expect(screen.getByText('旧版正文 A')).toBeVisible()
    expect(screen.queryByRole('button', { name: '编辑' })).not.toBeInTheDocument()
  })

  it('sends a versioned, field-only Wiki patch and keeps the draft on conflict', async () => {
    const user = open(`/projects/${a}/wiki/DOC-1?mode=edit`)
    const summary = await screen.findByRole('textbox', { name: '摘要' })
    await user.clear(summary)
    await user.type(summary, '新摘要')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('当前 Wiki 版本已变化。草稿已保留。')
    expect(summary).toHaveValue('新摘要')
    const patch = fetchMock.mock.calls.find(([url, opts]) => url === `/api/v2/projects/${a}/wiki/DOC-1` && opts?.method === 'PATCH')
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ expected_version: 4, patch: { summary: '新摘要' } })
  })

  it('creates a Wiki from the scoped v2 list', async () => {
    const user = open(`/projects/${a}/wiki`)
    expect(await screen.findByRole('link', { name: /同码 Wiki A/ })).toHaveAttribute('href', `/projects/${a}/wiki/DOC-1`)
    await user.click(screen.getByRole('link', { name: '新建 Wiki' }))
    await user.type(screen.getByRole('textbox', { name: '标题' }), '新手册')
    await user.type(screen.getByRole('textbox', { name: '标签' }), '维护，内部')
    await user.type(screen.getByRole('textbox', { name: 'Markdown 正文' }), '新建正文')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('heading', { name: '同码 Wiki A' })).toBeVisible()
    const post = fetchMock.mock.calls.find(([url, opts]) => url === `/api/v2/projects/${a}/wiki` && opts?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      title: '新手册', body: '新建正文', summary: null, category: null, tags: ['维护', '内部'],
      parent_id: null, request_id: expect.any(String),
    })
  })

  it('does not revive a missing canonical document from the old Wiki service', async () => {
    open(`/projects/${a}/wiki/DOC-404`)
    expect(await screen.findByRole('alert')).toHaveTextContent('Wiki 不存在')
    expect(fetchMock.mock.calls.some(([path]) => path.startsWith('/api/documents/wiki/'))).toBe(false)
  })

  it('loads bounded Wiki revision history and restores the selected snapshot', async () => {
    const user = open(`/projects/${a}/wiki/DOC-1`)
    await user.click(await screen.findByRole('button', { name: '版本历史' }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText('版本 4 · 新标题')).toBeVisible()
    await user.click(dialog.getByRole('button', { name: '加载旧版本' }))
    await user.click(await dialog.findByRole('button', { name: '版本 2 · 旧标题' }))
    expect(await dialog.findByText('第 2 版正文')).toBeVisible()
    await user.click(dialog.getByRole('button', { name: '恢复到版本 2' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const versionApi = `/api/v2/projects/${a}/wiki/DOC-1/versions`
    expect(fetchMock).toHaveBeenCalledWith(`${versionApi}?limit=20&before=4`, expect.anything())
    expect(fetchMock).toHaveBeenCalledWith(`${versionApi}/2/restore`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ expected_version: 4 }) }))
  })

  it('moves Wiki to a selected parent without offering a visible descendant', async () => {
    const user = open(`/projects/${a}/wiki/DOC-1`)
    await user.click(await screen.findByRole('button', { name: '移动' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.click(await dialog.findByRole('button', { name: 'DOC-2 · 新上级 Wiki' }))
    expect(dialog.queryByRole('button', { name: /自身子 Wiki/ })).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: '确认移动' }))
    expect(await screen.findByRole('link', { name: '上级 DOC-2' })).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(`/api/v2/projects/${a}/wiki/DOC-1/location`,
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ expected_version: 4, parent_id: 'DOC-2' }) }))
  })

  it('rechecks changed delete impact and restores the deleted Wiki through trash detail', async () => {
    const user = open(`/projects/${a}/wiki/DOC-1`)
    await user.click(await screen.findByRole('button', { name: '删除' }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText(/会影响 2 篇 Wiki/)).toBeVisible()
    await user.click(dialog.getByRole('button', { name: '确认删除' }))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Wiki 删除范围已变化')
    expect(dialog.getByRole('button', { name: '确认删除' })).toBeDisabled()
    await user.click(dialog.getByRole('button', { name: '重新检查影响' }))
    expect(await dialog.findByText(/会影响 3 篇 Wiki/)).toBeVisible()
    await user.click(dialog.getByRole('button', { name: '确认删除' }))
    await user.click(await screen.findByRole('link', { name: '回收站' }))
    await user.click(await screen.findByRole('link', { name: 'DOC-1 · 同码 Wiki A' }))
    expect(await screen.findByText('正文 A')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '恢复 Wiki' }))
    expect(await screen.findByRole('heading', { name: '同码 Wiki A' })).toBeVisible()
    const apiPath = `/api/v2/projects/${a}/wiki`
    expect(fetchMock).toHaveBeenCalledWith(`${apiPath}/DOC-1?confirmed_count=2`, expect.objectContaining({ method: 'DELETE' }))
    expect(fetchMock).toHaveBeenCalledWith(`${apiPath}/DOC-1?confirmed_count=3`, expect.objectContaining({ method: 'DELETE' }))
    expect(fetchMock).toHaveBeenCalledWith(`${apiPath}/trash/DOC-1/restore`, expect.objectContaining({ method: 'POST' }))
  })

  it('lets viewers read version history while keeping Wiki write actions and trash unavailable', async () => {
    const user = open(`/projects/${b}/wiki/DOC-1`)
    await user.click(await screen.findByRole('button', { name: '版本历史' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.click(await dialog.findByRole('button', { name: '加载旧版本' }))
    await user.click(await dialog.findByRole('button', { name: '版本 2 · 旧标题' }))
    expect(await dialog.findByText('第 2 版正文')).toBeVisible()
    expect(dialog.queryByRole('button', { name: /恢复到版本/ })).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: '关闭' }))
    expect(screen.queryByRole('button', { name: '移动' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: '打开 B 回收站' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('没有权限访问 Wiki 回收站')
    expect(fetchMock.mock.calls.some(([path]) => path.includes('/wiki/trash'))).toBe(false)
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

  it('browses and uploads files in the selected project library', async () => {
    const attempts = mockUploadRequests()
    const user = open(`/projects/${a}/files`)
    expect(await screen.findByRole('heading', { name: '项目文件' })).toBeVisible()
    expect(await screen.findByRole('link', { name: '橘猫.png' })).toHaveAttribute('href', `/projects/${a}/files/${attachment}`)
    expect(screen.queryByText('其他项目图片')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '只看图片' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v2/projects/${a}/files?query=&limit=20&images_only=true`, expect.anything()))
    const file = new File(['file bytes'], '新图片.png', { type: 'image/png' })
    await user.upload(screen.getByLabelText('选择项目文件'), file)
    expect(await screen.findByRole('progressbar', { name: '项目文件上传进度' })).toHaveAttribute('value', '50')
    expect(attempts[0].body).toBe(file)
    await act(async () => attempts[0].finish(201))
    expect(screen.getByRole('status')).toHaveTextContent('已上传 橘猫.png')
  })

  it('views deleted file metadata and restores it through its scoped project library', async () => {
    const user = open(`/projects/${a}/files?state=deleted`)
    expect(await screen.findByRole('heading', { name: '文件回收站' })).toBeVisible()
    const details = await screen.findByRole('button', { name: '查看 橘猫.png 详情' })
    await user.click(details)
    expect(details).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('77777777-7777-4777-8777-777777777777')).toBeVisible()
    expect(screen.getByText('删除时间').nextElementSibling?.querySelector('time')).toHaveAttribute('datetime', timestamp)
    expect(screen.queryByRole('link', { name: '下载 橘猫.png' })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`/api/v2/projects/${a}/files/${attachment}/trash`, expect.anything())
    await user.click(screen.getByRole('button', { name: '恢复 橘猫.png' }))
    expect(await screen.findByText('没有可恢复的文件')).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(`/api/v2/projects/${a}/files/${attachment}/restore`,
      expect.objectContaining({ method: 'POST' }))
  })

  it('opens the selected Wiki snapshot from a historical file usage link', async () => {
    const user = open(`/projects/${a}/files/${attachment}`)
    expect(await screen.findByRole('link', { name: '设计手册' })).toBeVisible()
    expect(screen.queryByText('其他项目引用')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '包含历史版本' }))
    await user.click(await screen.findByRole('link', { name: '设计手册 · v2' }))
    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText('第 2 版正文')).toBeVisible()
    await user.click(dialog.getByRole('button', { name: '关闭' }))
    expect(await screen.findByRole('heading', { name: '同码 Wiki A' })).toBeVisible()
  })

  it('opens the exact historical timeline revision from file usage and returns to recent entries', async () => {
    const user = open(`/projects/${a}/files/${attachment}`)
    await user.click(await screen.findByRole('button', { name: '包含历史版本' }))
    await user.click(await screen.findByRole('link', { name: '需求时间轴 · v1' }))
    expect(await screen.findByText('引用文件时的原始正文')).toBeVisible()
    expect(screen.queryByText('较早记录的完整正文')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '返回最新记录' }))
    expect(await screen.findByText('近期回复')).toBeVisible()
    expect(screen.queryByText('引用文件时的原始正文')).not.toBeInTheDocument()
  })

  it('shows cross-reference impact before deleting the scoped file', async () => {
    const user = open(`/projects/${a}/files/${attachment}`)
    await user.click(await screen.findByRole('button', { name: '重命名' }))
    const rename = within(await screen.findByRole('dialog'))
    const name = rename.getByRole('textbox', { name: '文件名称' })
    await user.clear(name)
    await user.type(name, '更新文件名.png')
    await user.click(rename.getByRole('button', { name: '保存名称' }))
    expect(await screen.findByRole('heading', { name: '更新文件名.png' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '删除' }))
    const confirmation = within(await screen.findByRole('dialog'))
    expect(await confirmation.findByRole('link', { name: '设计手册 · v2' })).toBeVisible()
    expect(confirmation.queryByText('其他项目引用')).not.toBeInTheDocument()
    await user.click(confirmation.getByRole('button', { name: '确认删除' }))
    expect(await screen.findByRole('heading', { name: '项目文件' })).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(`/api/v2/projects/${a}/files/${attachment}`, expect.objectContaining({ method: 'DELETE' }))
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

  it('opens a notification or search hash directly in the record context', async () => {
    open(`/projects/${a}/requirements/REQ-1#timeline-${older}`)
    expect(await screen.findByText('较早记录的完整正文')).toBeVisible()
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
