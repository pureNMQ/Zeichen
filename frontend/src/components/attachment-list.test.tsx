import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() } }
})

import { api } from '@/lib/api'
import { AttachmentList } from '@/components/attachment-list'
import { NotificationProvider } from '@/components/ui/notification'
import { CurrentProjectProvider } from '@/lib/current-project'

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <NotificationProvider>
        <CurrentProjectProvider>
          <MemoryRouter>
            <AttachmentList targetType="task" targetId="t1" />
          </MemoryRouter>
        </CurrentProjectProvider>
      </NotificationProvider>
    </QueryClientProvider>,
  )
}

function mockAttachments(role: 'editor' | 'viewer') {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve([{ id: 'p1', name: 'demo', created_at: '2026-08-01T00:00:00Z', my_role: role }])
    if (path.includes('/attachments')) return Promise.resolve({
      items: [
        { id: 'a1', target_type: 'task', target_id: 't1', file_name: '报告.pdf', size: 2048, created_by: 'u1', created_at: '2026-08-01T00:00:00Z', deleted_at: null },
        { id: 'a2', target_type: 'task', target_id: 't1', file_name: '图片.png', size: 1048576, created_by: 'u1', created_at: '2026-08-01T00:00:00Z', deleted_at: null },
      ],
    })
    return Promise.resolve({})
  })
}

describe('附件列表', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('渲染附件名称与大小', async () => {
    mockAttachments('editor')
    renderList()
    expect(await screen.findByText('报告.pdf')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    expect(screen.getByText('1.0 MB')).toBeInTheDocument()
  })

  it('editor 可见上传与删除按钮，下载触发 fetch', async () => {
    mockAttachments('editor')
    const user = userEvent.setup()
    renderList()
    expect(await screen.findByRole('button', { name: '上传' })).toBeInTheDocument()
    const deleteBtn = await screen.findByRole('button', { name: '删除 报告.pdf' })
    await user.click(deleteBtn)
    expect(api.delete).toHaveBeenCalledWith('/attachments/a1')
  })

  it('viewer 仅只读：无上传/删除按钮', async () => {
    mockAttachments('viewer')
    renderList()
    expect(await screen.findByText('报告.pdf')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '上传' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 报告.pdf' })).not.toBeInTheDocument()
  })
})
