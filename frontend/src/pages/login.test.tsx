import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '@/lib/auth'
import { LoginPage } from '@/pages/login'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError,
    api: {
      get: vi.fn().mockRejectedValue(new ApiError(401, '未登录')),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }
})

import { api, type LoginResponse } from '@/lib/api'

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/projects" element={<div>项目页</div>} />
          <Route path="/set-password" element={<div>设置密码页</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const me = {
  id: 'u1',
  username: 'admin',
  is_agent: false,
  workspace_role: 'admin' as const,
}

describe('LoginPage 登录流', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockRejectedValue({ status: 401 })
  })

  it('渲染表单并提交登录', async () => {
    vi.mocked(api.post).mockResolvedValue({ needs_password: false, user: me })
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText('账号'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'admin-pass-1')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(api.post).toHaveBeenCalledWith('/auth/login', {
      username: 'admin',
      password: 'admin-pass-1',
    })
    expect(await screen.findByText('项目页')).toBeInTheDocument()
  })

  it('未设密码的成员跳转设置密码页', async () => {
    vi.mocked(api.post).mockResolvedValue({ needs_password: true } as LoginResponse)
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText('账号'), 'bob')
    await user.type(screen.getByLabelText('密码'), 'whatever-1')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('设置密码页')).toBeInTheDocument()
  })

  it('凭证错误时展示错误信息', async () => {
    const { ApiError } = await import('@/lib/api')
    vi.mocked(api.post).mockRejectedValue(new ApiError(401, '用户名或密码错误'))
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText('账号'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'wrong-pass-123')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
  })
})
