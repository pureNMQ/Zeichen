import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { api } from '@/lib/api'
import { NotificationBell } from '@/components/notification-bell'
import { NotificationProvider } from '@/components/ui/notification'

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }))

const path = '/projects/project-a/requirements/REQ-1#timeline-entry'
const reply = {
  id: 'n1', source_kind: 'timeline', source_code: 'REQ-1', source_path: path,
  visibility: 'shared', read_at: null, reply_user_id: 'owner',
}
const mention = {
  id: 'n2', source_kind: 'wiki', source_code: 'DOC-2',
  source_path: '/projects/project-a/wiki/DOC-2',
  visibility: 'owner_only', read_at: null, reply_user_id: null,
}

function CurrentLocation() {
  const location = useLocation()
  return <output>{location.pathname}{location.search}{location.hash}</output>
}

function renderBell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <NotificationProvider>
        <MemoryRouter>
          <NotificationBell />
          <CurrentLocation />
        </MemoryRouter>
      </NotificationProvider>
    </QueryClientProvider>,
  )
}

describe('通知铃铛', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === '/v2/notifications/unread-count') return Promise.resolve({ count: 1 })
      if (url.includes('cursor=next')) return Promise.resolve({ items: [mention], next_cursor: null })
      return Promise.resolve({ items: [reply], next_cursor: 'next' })
    })
  })

  it('展开和翻页都不标记已读', async () => {
    renderBell()
    const user = userEvent.setup()
    expect(await screen.findByText('1')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '通知' }))
    expect(await screen.findByText(/回复了你的记录/)).toBeInTheDocument()
    await user.click(screen.getByRole('menuitem', { name: '加载更多' }))
    expect(await screen.findByText(/仅主人可见/)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('打开后跳转到服务端重新授权的项目和记录', async () => {
    vi.mocked(api.post).mockResolvedValue(reply)
    renderBell()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '通知' }))
    await user.click(await screen.findByText(/回复了你的记录/))
    expect(api.post).toHaveBeenCalledWith('/v2/notifications/n1/open')
    expect(await screen.findByText(path)).toBeInTheDocument()
  })

  it.each([
    ['requirement', '需求正文', 'REQ-1', '/projects/project-a/requirements/REQ-1?tab=body'],
    ['task', '任务正文', 'REQ-1-T1', '/projects/project-a/tasks/REQ-1-T1'],
  ])('正文提及显示来源并打开对应正文：%s', async (kind, label, code, sourcePath) => {
    const notice = { ...mention, source_kind: kind, source_code: code, source_path: sourcePath }
    vi.mocked(api.get).mockImplementation(url => Promise.resolve(url.endsWith('unread-count')
      ? { count: 1 } : { items: [notice], next_cursor: null }))
    vi.mocked(api.post).mockResolvedValue(notice)
    renderBell()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '通知' }))
    await user.click(await screen.findByRole('menuitem', { name: new RegExp(label) }))
    expect(await screen.findByText(sourcePath)).toBeInTheDocument()
  })

  it('来源权限变化时给出错误反馈并留在原页', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('通知来源已不可见'))
    renderBell()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '通知' }))
    await user.click(await screen.findByText(/回复了你的记录/))
    expect(await screen.findByText('通知来源已不可见')).toBeInTheDocument()
    expect(screen.queryByText(path)).not.toBeInTheDocument()
  })
})
