import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), upload: vi.fn() },
  } as unknown as typeof actual
})

import { api } from '@/lib/api'
import { NotificationPreferencesDialog } from '@/components/notification-preferences-dialog'
import { WatchButton } from '@/components/watch-button'

function render(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('通知偏好对话框(REQ 023b607e)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({
      domains: { requirement: true, task: true, document: false, project: true },
      actions: { create: true, update: true, status: true, comment: true, reference: true, assign: true, claim: true, delete: true, restore: true, move: true },
    })
    vi.mocked(api.put).mockResolvedValue({})
  })

  it('加载当前偏好并保存修改', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    render(<NotificationPreferencesDialog open onOpenChange={onOpenChange} />)

    const documentCheckbox = await screen.findByRole('checkbox', { name: '文档' })
    expect(documentCheckbox).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: '需求' })).toBeChecked()

    await user.click(documentCheckbox)
    await user.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith('/users/me/notification-preferences', {
        domains: { requirement: true, task: true, document: true, project: true },
        actions: expect.objectContaining({ create: true }),
      })
    })
  })
})

describe('关注按钮(REQ 023b607e)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('未关注时点击发起关注并刷新状态', async () => {
    const user = userEvent.setup()
    vi.mocked(api.get).mockResolvedValue({ watching: false })
    vi.mocked(api.post).mockResolvedValue({ watching: true })
    render(<WatchButton targetType="requirement" targetId="r1" />)

    const button = await screen.findByRole('button', { name: '关注' })
    expect(button).toHaveAttribute('aria-pressed', 'false')
    await user.click(button)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/targets/requirement/r1/watch'))
  })

  it('已关注时显示取消关注', async () => {
    vi.mocked(api.get).mockResolvedValue({ watching: true })
    render(<WatchButton targetType="task" targetId="t1" />)
    expect(await screen.findByRole('button', { name: '取消关注' })).toHaveAttribute('aria-pressed', 'true')
  })
})
