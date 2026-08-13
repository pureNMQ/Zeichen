import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return {
    ApiError,
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() },
    STATUS_LABEL: { backlog: '待办', in_progress: '实现中', verifying: '验收中', done: '已完成', cancelled: '已取消' },
  }
})

import { api, STATUS_LABEL, type ActivityRow, type CommentRow, type WorkflowStatus } from '@/lib/api'
import { ActivityStream } from '@/components/activity-stream'
import { CommentStream } from '@/components/comment-stream'
import { StatusBadge } from '@/components/status-badge'
import { StatusSelect } from '@/components/status-select'
import { NotificationProvider } from '@/components/ui/notification'

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <NotificationProvider>{node}</NotificationProvider>
    </QueryClientProvider>,
  )
}

describe('ActivityStream', () => {
  const rows: ActivityRow[] = [
    { id: 'a1', target_type: 'task', target_id: 't1', actor_id: 'u1', actor: 'admin', action: 'create', summary: '创建任务', created_at: '2026-08-01T00:00:00Z' },
    { id: 'a2', target_type: 'task', target_id: 't1', actor_id: 'u2', actor: 'agent-a', action: 'weird_action', summary: '未知动作', created_at: '2026-08-01T00:00:00Z' },
  ]

  it('渲染活动并回退未知动作原文', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: rows })
    wrap(<ActivityStream targetType="task" targetId="t1" />)
    expect(await screen.findByText('创建')).toBeInTheDocument()
    expect(screen.getByText('admin')).toBeInTheDocument()
    expect(screen.getByText('weird_action')).toBeInTheDocument()
    expect(screen.getByText(/— 创建任务/)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/targets/task/t1/activity?limit=50')
  })
})

describe('CommentStream', () => {
  const comments: CommentRow[] = [
    { id: 'c1', target_type: 'task', target_id: 't1', author_id: 'u1', author: 'admin', body: '第一版说明', created_at: '2026-08-01T00:00:00Z' },
  ]

  it('只读视角不渲染评论表单', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: comments })
    wrap(<CommentStream targetType="task" targetId="t1" canEdit={false} />)
    expect(await screen.findByText('第一版说明')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '发表评论' })).not.toBeInTheDocument()
  })

  it('编辑权下可发表评论并清空输入', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: comments })
    vi.mocked(api.post).mockResolvedValue({})
    const user = userEvent.setup()
    wrap(<CommentStream targetType="task" targetId="t1" canEdit />)
    await user.type(await screen.findByPlaceholderText('写评论…'), '补充评论')
    await user.click(screen.getByRole('button', { name: '发表评论' }))
    expect(api.post).toHaveBeenCalledWith('/targets/task/t1/comments', { body: '补充评论' })
    expect(vi.mocked(api.get)).toHaveBeenCalled()
  })

  it('空评论按钮禁用', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [] })
    wrap(<CommentStream targetType="task" targetId="t1" canEdit />)
    const button = await screen.findByRole('button', { name: '发表评论' })
    expect(button).toBeDisabled()
  })

  it('发表失败显示通知并可关闭', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [] })
    vi.mocked(api.post).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    wrap(<CommentStream targetType="task" targetId="t1" canEdit />)
    await user.type(await screen.findByPlaceholderText('写评论…'), '会失败的评论')
    await user.click(screen.getByRole('button', { name: '发表评论' }))
    expect(await screen.findByText('评论失败')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '关闭提示' }))
    expect(screen.queryByText('评论失败')).not.toBeInTheDocument()
  })
})

describe('StatusBadge', () => {
  it.each<WorkflowStatus>(['backlog', 'in_progress', 'verifying', 'done', 'cancelled'])(
    '渲染 %s 的中文标签',
    (status) => {
      wrap(<StatusBadge status={status} />)
      expect(screen.getByText(STATUS_LABEL[status])).toBeInTheDocument()
    },
  )
})

describe('StatusSelect', () => {
  it('渲染当前值并触发选择回调', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    wrap(
      <StatusSelect
        value="in_progress"
        statuses={['backlog', 'in_progress', 'done']}
        onSelect={onSelect}
        ariaLabel="任务状态"
      />,
    )
    await user.click(screen.getByRole('combobox', { name: '任务状态' }))
    const option = await screen.findByText(STATUS_LABEL.done)
    await user.click(option)
    expect(onSelect).toHaveBeenCalledWith('done')
  })

  it('禁用态不响应点击', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    wrap(<StatusSelect value="backlog" statuses={['backlog', 'done']} onSelect={onSelect} disabled />)
    expect(screen.getByRole('combobox', { name: '状态' })).toBeDisabled()
    await user.click(screen.getByRole('combobox', { name: '状态' }))
    expect(screen.queryByText(STATUS_LABEL.done)).not.toBeInTheDocument()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
