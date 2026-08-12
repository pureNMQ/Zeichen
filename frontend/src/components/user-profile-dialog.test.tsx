import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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
    api: { patch: vi.fn(), upload: vi.fn(), delete: vi.fn() },
  }
})

import { api, ApiError } from '@/lib/api'
import { NotificationProvider } from '@/components/ui/notification'
import { UserProfileDialog } from './user-profile-dialog'

const profile = { id: 'u1', username: 'puremi', nickname: null, avatar: null }

function renderDialog() {
  return render(
    <NotificationProvider>
      <UserProfileDialog user={profile} self open onOpenChange={vi.fn()} onSaved={vi.fn()} />
    </NotificationProvider>,
  )
}

describe('UserProfileDialog', () => {
  it('previews the selected image before it is saved', async () => {
    const createObjectURL = vi.fn(() => 'blob:avatar-preview')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    const user = userEvent.setup()
    renderDialog()

    await user.upload(screen.getByLabelText('头像'), new File(['image'], 'avatar.png', { type: 'image/png' }))

    expect(createObjectURL).toHaveBeenCalled()
    expect(document.querySelector('img')).toHaveAttribute('src', 'blob:avatar-preview')
  })

  it('uses a closable notification instead of inline error text when saving fails', async () => {
    vi.mocked(api.patch).mockRejectedValueOnce(new ApiError(404, 'Not Found'))
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole('button', { name: '保存资料' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Not Found')
    expect(screen.getByRole('button', { name: '关闭提示' })).toBeInTheDocument()
    expect(screen.queryByText('Not Found', { selector: 'form p' })).not.toBeInTheDocument()
  })

  it('previews the default avatar and removes the uploaded avatar only when saved', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce(undefined)
    const onOpenChange = vi.fn()
    const onSaved = vi.fn()
    const user = userEvent.setup()

    render(
      <NotificationProvider>
        <UserProfileDialog
          user={{ ...profile, avatar: '/api/users/u1/avatar?v=1' }}
          self
          open
          onOpenChange={onOpenChange}
          onSaved={onSaved}
        />
      </NotificationProvider>,
    )

    await user.click(screen.getByRole('button', { name: '恢复默认头像' }))

    expect(api.delete).not.toHaveBeenCalled()
    expect(document.querySelector('img')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '保存资料' }))

    expect(api.delete).toHaveBeenCalledWith('/users/me/avatar')
    expect(onSaved).toHaveBeenCalledOnce()
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
