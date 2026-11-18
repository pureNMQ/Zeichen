import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  },
  api: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ refresh: vi.fn() }),
}))

import { api, ApiError } from '@/lib/api'
import { SetPasswordPage } from '@/pages/set-password'

function openSetup() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/set-password?token=abcdefghijklmnopqrstuvwxyz123456']}>
        <Routes><Route path="/set-password" element={<SetPasswordPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SetPasswordPage', () => {
  it('通过一次性链接显示对应账号', async () => {
    vi.mocked(api.get).mockResolvedValue({ username: 'carol' })
    openSetup()

    expect(await screen.findByText('为账号 carol 设置首次密码')).toBeInTheDocument()
  })

  it('无效的一次性链接显示失效页而不是密码表单', async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(401, 'Link expired'))
    openSetup()

    expect(await screen.findByText('设密链接已失效或不存在')).toBeInTheDocument()
    expect(screen.queryByLabelText('新密码(至少 8 位)')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存并进入' })).not.toBeInTheDocument()
  })

  it('lets the user retry after a temporary validation error', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(503, 'Unavailable')).mockResolvedValueOnce({ username: 'carol' })
    const user = userEvent.setup()
    openSetup()
    await user.click(await screen.findByRole('button', { name: '重试验证' }))
    expect(await screen.findByText('为账号 carol 设置首次密码')).toBeInTheDocument()
  })
})
