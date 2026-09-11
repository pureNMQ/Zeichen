import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {}
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

import { api } from '@/lib/api'
import { CreateTaskDialog } from '@/components/create-task-dialog'
import { CurrentProjectProvider } from '@/lib/current-project'

function renderDialog(open: boolean, presetRequirementId: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CurrentProjectProvider>
        <CreateTaskDialog open={open} onOpenChange={() => {}} presetRequirementId={presetRequirementId} />
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

describe('任务创建表单草稿暂存(REQ ff7a0aa2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve([{ id: 'p1', name: 'P', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' }])
      if (path.startsWith('/projects/p1/requirements')) return Promise.resolve({ items: [], next_cursor: null })
      return Promise.resolve({ items: [], next_cursor: null })
    })
    localStorage.setItem('zeichen.currentProjectId', 'p1')
  })

  it('输入内容自动入草稿,重开对话框自动恢复', async () => {
    const user = userEvent.setup()
    const { rerender } = renderDialog(true)
    await user.type(await screen.findByLabelText('标题'), '未提交的任务标题')
    await user.type(screen.getByLabelText('描述'), '未提交的描述')
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem('zeichen.draft.task:p1')!)).toEqual({ title: '未提交的任务标题', description: '未提交的描述', requirementId: null })
    })

    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <CurrentProjectProvider>
          <CreateTaskDialog open={false} onOpenChange={() => {}} />
        </CurrentProjectProvider>
      </QueryClientProvider>,
    )
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <CurrentProjectProvider>
          <CreateTaskDialog open onOpenChange={() => {}} />
        </CurrentProjectProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByLabelText('标题')).toHaveValue('未提交的任务标题')
    expect(screen.getByLabelText('描述')).toHaveValue('未提交的描述')
  })

  it('「清空草稿」按钮清空存储并重置表单', async () => {
    const user = userEvent.setup()
    renderDialog(true)
    await user.type(await screen.findByLabelText('标题'), '草稿内容')
    await waitFor(() => expect(localStorage.getItem('zeichen.draft.task:p1')).not.toBeNull())

    await user.click(screen.getByRole('button', { name: '清空草稿' }))
    expect(localStorage.getItem('zeichen.draft.task:p1')).toBeNull()
    expect(screen.getByLabelText('标题')).toHaveValue('')
  })

  it('创建成功后清除草稿', async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockResolvedValue({ id: 't1' })
    renderDialog(true)
    await user.type(await screen.findByLabelText('标题'), '将提交的标题')
    await user.click(screen.getByRole('button', { name: /创建/ }))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    await waitFor(() => expect(localStorage.getItem('zeichen.draft.task:p1')).toBeNull())
  })
})
