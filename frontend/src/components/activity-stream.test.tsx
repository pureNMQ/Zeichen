import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', () => ({ api: { get: vi.fn() } }))

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

  const summary = screen.getByText((content, element) => element?.tagName === 'SPAN' && (element.textContent ?? '').startsWith('—'))
  expect(summary).toHaveClass('truncate')
  expect(summary).toHaveClass('min-w-0')

  expect(screen.getByText('评论')).toBeInTheDocument()
})
