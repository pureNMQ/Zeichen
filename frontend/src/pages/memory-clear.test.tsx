import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
import { MemoryPage } from '@/pages/memory'

// REQ-4 要点 1(前端):记忆管理页「清空」按钮。
// 契约(前端需求 v1.0 §3.4):二次确认;确认框明确显示清空范围=当前项目全部共享记忆;
// 确认后调用 DELETE /projects/{id}/memory 且携带 confirmed=true(与执行范围一致)。
// 现有页面无清空入口,以下用例红灯。

function renderMemory(entry = '/memory') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CurrentProjectProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/memory" element={<MemoryPage />} />
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
      items: [{ id: 'memory-1', content: '初始内容', created_at: '2026-08-01T00:00:00Z', external_metadata: { source_id: 'agent-1', source_name: '检索 Agent', source_kind: 'agent' } }],
    })
    return Promise.resolve({ items: [] })
  })
}

describe('记忆管理页清空', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('提供清空入口,确认框明示范围为当前项目全部共享记忆,确认后携带 confirmed 调用', async () => {
    const user = userEvent.setup()
    mockProjectAndMemory()
    renderMemory()

    await user.click(await screen.findByRole('button', { name: '清空记忆' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('当前项目')
    expect(dialog).toHaveTextContent('全部共享记忆')

    await user.click(screen.getByRole('button', { name: '清空' }))
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(expect.stringMatching(/\/projects\/p1\/memory.*confirmed=true/)),
    )
  })

  it('确认框提供取消且取消后不调用清空接口', async () => {
    const user = userEvent.setup()
    mockProjectAndMemory()
    renderMemory()

    await user.click(await screen.findByRole('button', { name: '清空记忆' }))
    await user.click(await screen.findByRole('button', { name: '取消' }))

    expect(await screen.findByText('初始内容')).toBeInTheDocument()
    expect(api.delete).not.toHaveBeenCalled()
  })
})
