import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { get: vi.fn(), post: actual.api.post, delete: actual.api.delete },
  } as unknown as typeof actual
})

import { ActivityStream } from '@/components/activity-stream'
import { api, type ActivityRow } from '@/lib/api'

it('活动行垂直居中对齐,长摘要以 min-w-0 截断不破坏布局', async () => {
  const row: ActivityRow = {
    id: 'a1',
    target_type: 'task',
    target_id: 't1',
    actor_id: 'u1',
    actor: 'alice',
    actor_avatar: null,
    action: 'comment',
    summary: '很长的摘要'.repeat(80),
    created_at: '2026-09-01T00:00:00Z',
  }
  vi.mocked(api.get).mockResolvedValue({ items: [row] })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ActivityStream targetType="task" targetId="t1" />
    </QueryClientProvider>,
  )

  const line = (await screen.findByText('alice')).closest('div')!
  expect(line).toHaveClass('items-center')
  expect(line).not.toHaveClass('items-baseline')

  const summary = screen.getByText((_content, element) => element?.tagName === 'SPAN' && (element.textContent ?? '').startsWith('—'))
  expect(summary).toHaveClass('truncate')
  expect(summary).toHaveClass('min-w-0')

  expect(screen.getByText('评论')).toBeInTheDocument()
})

it('历史英文状态摘要与引用目标映射为中文,动作 status 显示「变更状态」', async () => {
  const rows: ActivityRow[] = [
    { id: 'a1', target_type: 'requirement', target_id: 'r1', actor_id: 'u1', actor: 'alice', actor_avatar: null, action: 'status', summary: 'pending → backlog', created_at: '2026-09-01T00:00:00Z' },
    { id: 'a2', target_type: 'requirement', target_id: 'r1', actor_id: 'u2', actor: 'bob', actor_avatar: null, action: 'reference', summary: '引用 document:6b337384-c9fa-4bc6-934c-1b90ceea323b', created_at: '2026-09-01T00:01:00Z' },
    { id: 'a3', target_type: 'requirement', target_id: 'r1', actor_id: 'u3', actor: 'carol', actor_avatar: null, action: 'status', summary: '待办 → 已完成', created_at: '2026-09-01T00:02:00Z' },
  ]
  vi.mocked(api.get).mockResolvedValue({ items: rows })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ActivityStream targetType="requirement" targetId="r1" />
    </QueryClientProvider>,
  )

  expect(await screen.findByText('— 待确认 → 待办')).toBeInTheDocument()
  expect(screen.getAllByText('变更状态').length).toBe(2)
  expect(screen.getByText('— 引用 文档:6b337384…')).toBeInTheDocument()
  expect(screen.getByText('— 待办 → 已完成')).toBeInTheDocument()
  expect(screen.queryByText(/pending/)).not.toBeInTheDocument()
})
