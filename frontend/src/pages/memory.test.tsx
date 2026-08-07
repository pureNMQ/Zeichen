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
import { MemoryPage, MemorySessionsPage } from '@/pages/memory'

function renderMemory(entry = '/memory') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/memory/sessions" element={<MemorySessionsPage />} />
          </Routes>
        </MemoryRouter>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

function mockProjectAndMemory() {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve([{ id: 'p1', name: '示例项目', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' }])
    if (path === '/projects/p1/memory') return Promise.resolve({
      items: [{ id: 'memory-1', content: '初始内容', created_at: '2026-08-01T00:00:00Z', external_metadata: { source_id: 'agent-1', source_name: '检索 Agent', source_kind: 'agent', entity_type: 'task', entity_id: 'task-1' } }],
    })
    return Promise.resolve({ items: [] })
  })
}

describe('记忆管理页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('将长期记忆作为默认页，并在详情抽屉中确认删除', async () => {
    const user = userEvent.setup()
    mockProjectAndMemory()
    renderMemory()

    expect(await screen.findByRole('link', { name: '长期记忆' })).toHaveAttribute('href', '/memory')
    expect(screen.getByRole('link', { name: '会话缓存' })).toHaveAttribute('href', '/memory/sessions')
    expect(await screen.findByText('初始内容')).toBeInTheDocument()
    expect(screen.getByText('锚点：')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除记忆' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '查看记忆详情 memory-1' }))
    expect(await screen.findByRole('heading', { name: '记忆详情' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '删除记忆' }))
    expect(await screen.findByRole('heading', { name: '删除这条记忆？' })).toBeInTheDocument()
  })

  it('在长期记忆为空时引导前往会话缓存', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve([{ id: 'p1', name: '示例项目', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' }])
      if (path === '/projects/p1/memory') return Promise.resolve({ items: [] })
      return Promise.resolve({ items: [] })
    })
    renderMemory()

    expect(await screen.findByRole('link', { name: '前往会话缓存' })).toHaveAttribute('href', '/memory/sessions')
  })

  it('在独立会话缓存页显示摘要、详情与蒸馏操作', async () => {
    const user = userEvent.setup()
    const rawSessionId = 'zeichen:p1:agent-1:release'
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve([{ id: 'p1', name: '示例项目', created_at: '2026-08-01T00:00:00Z', my_role: 'editor' }])
      if (path === '/projects/p1/memory/sessions') return Promise.resolve({ items: [{ session_id: rawSessionId, business_session_id: 'release', source_name: '检索 Agent', effective_status: 'running', last_activity_at: '2026-08-07T02:12:11Z', preview: '发布口令是什么？ · jade-orbit-42' }] })
      if (path === `/projects/p1/memory/sessions/${encodeURIComponent(rawSessionId)}`) return Promise.resolve({ qas: [{ time: '2026-08-07T02:11:28Z', question: '发布口令是什么？', answer: 'jade-orbit-42' }], traces: [] })
      return Promise.resolve({ items: [] })
    })
    vi.mocked(api.post).mockResolvedValue({ job: { id: 'job-1', status: 'queued' } })
    renderMemory('/memory/sessions')

    expect(await screen.findByText('发布口令是什么？ · jade-orbit-42')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看会话缓存 release' }))
    expect(await screen.findByText('问：发布口令是什么？')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '蒸馏为长期记忆' })).toBeInTheDocument()
  })
})
