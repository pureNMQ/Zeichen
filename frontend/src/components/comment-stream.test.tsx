import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {}
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }
})

import { CommentStream } from '@/components/comment-stream'
import { NotificationProvider } from '@/components/ui/notification'
import { api } from '@/lib/api'

it('评论删除失败显示可关闭的应用内通知', async () => {
  vi.mocked(api.get).mockResolvedValue({ items: [{ id: 'c1', body: '内容', author: 'admin', author_id: 'u1', created_at: '2026-08-01T00:00:00Z' }] })
  vi.mocked(api.delete).mockRejectedValue(new Error('删除失败'))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<NotificationProvider><QueryClientProvider client={queryClient}><CommentStream targetType="task" targetId="t1" canEdit /></QueryClientProvider></NotificationProvider>)

  const user = (await import('@testing-library/user-event')).default
  await user.click(await screen.findByRole('button', { name: '删除评论' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('删除失败')
  await user.click(screen.getByRole('button', { name: '关闭提示' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
