import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  api: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ refresh: vi.fn() }),
}))

import { api } from '@/lib/api'
import { SetPasswordPage } from '@/pages/set-password'

describe('SetPasswordPage', () => {
  it('通过一次性链接显示对应账号', async () => {
    vi.mocked(api.get).mockResolvedValue({ username: 'carol' })
    render(
      <MemoryRouter initialEntries={['/set-password?token=abcdefghijklmnopqrstuvwxyz123456']}>
        <Routes>
          <Route path="/set-password" element={<SetPasswordPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('为账号 carol 设置首次密码')).toBeInTheDocument()
  })

  it('无效的一次性链接显示失效页而不是密码表单', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('not found'))
    render(
      <MemoryRouter initialEntries={['/set-password?token=abcdefghijklmnopqrstuvwxyz123456']}>
        <Routes>
          <Route path="/set-password" element={<SetPasswordPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('设密链接已失效或不存在')).toBeInTheDocument()
    expect(screen.queryByLabelText('新密码(至少 8 位)')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存并进入' })).not.toBeInTheDocument()
  })
})
