import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {}
  return {
  withProject: (path: string) => path, ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() } }
})
vi.mock('@/lib/project-files', () => ({ uploadAssociatedFile: vi.fn() }))

import { api } from '@/lib/api'
import { CreateTaskDialog } from '@/components/create-task-dialog'
import { CurrentProjectProvider } from '@/lib/current-project'
import { uploadAssociatedFile } from '@/lib/project-files'

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

describe('任务创建表单引用与附件回填(REQ ee290fae)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve([{ id: 'p1', name: 'P', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' }])
      if (path.startsWith('/projects/p1/requirements')) return Promise.resolve({ items: [{ id: 'r9', title: '目标需求', status: 'backlog', project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', task_count: 0 }], next_cursor: null })
      return Promise.resolve({ items: [], next_cursor: null })
    })
    localStorage.setItem('zeichen.currentProjectId', 'p1')
  })

  it('文件回填失败后重试同一任务、同一次附件上传', async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockResolvedValue({ id: 'new1' })
    vi.mocked(uploadAssociatedFile).mockRejectedValueOnce(new Error('断线')).mockResolvedValueOnce(undefined)
    renderDialog(true)

    await user.type(await screen.findByLabelText('标题'), '带关联的任务')
    await user.click(screen.getByRole('combobox', { name: '关联需求' }))
    await user.click(await screen.findByRole('option', { name: '目标需求' }))
    await user.click(screen.getByRole('combobox', { name: '引用目标' }))
    await user.click(await screen.findByRole('option', { name: '目标需求' }))
    await user.click(screen.getByRole('button', { name: '添加引用' }))
    expect(screen.getAllByText(/目标需求/).length).toBeGreaterThan(0)

    const file = new File(['hello'], 'spec.txt', { type: 'text/plain' })
    await user.upload(screen.getByLabelText('附件(可选,创建后上传)'), file)
    expect(screen.getByText('spec.txt')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /创建/ }))
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/targets/task/new1/references', {
        from_type: 'task', from_id: 'new1', to_type: 'requirement', to_id: 'r9', type: 'derives',
      })
      expect(uploadAssociatedFile).toHaveBeenCalledWith('p1', 'tasks', 'new1', { file, requestId: expect.any(String) })
    })
    expect(await screen.findByText('任务已创建。部分引用或附件保存失败，请重试。')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /创建/ }))
    await waitFor(() => expect(uploadAssociatedFile).toHaveBeenCalledTimes(2))
    expect(vi.mocked(uploadAssociatedFile).mock.calls[0]).toEqual(vi.mocked(uploadAssociatedFile).mock.calls[1])
    expect(vi.mocked(api.post).mock.calls.filter(([path]) => path === '/projects/p1/tasks')).toHaveLength(1)
    expect(api.upload).not.toHaveBeenCalled()
  })
})

describe('任务创建表单草稿暂存(REQ ff7a0aa2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') return Promise.resolve([{ id: 'p1', name: 'P', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' }])
      if (path.startsWith('/projects/p1/requirements')) return Promise.resolve({ items: [{ id: 'r9', title: '挂载需求', status: 'backlog', project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', task_count: 0 }], next_cursor: null })
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
    await user.click(screen.getByRole('combobox', { name: '关联需求' }))
    await user.click(await screen.findByRole('option', { name: '挂载需求' }))
    await user.click(screen.getByRole('button', { name: /创建/ }))
    await waitFor(() => expect(api.post).toHaveBeenCalled())
    await waitFor(() => expect(localStorage.getItem('zeichen.draft.task:p1')).toBeNull())
  })
})
