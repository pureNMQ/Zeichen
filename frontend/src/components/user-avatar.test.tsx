import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UserIdentityLabel } from './user-avatar'
import { identityName } from '@/lib/user-identity'

describe('user identity', () => {
  it('prefers nickname and keeps the account visible when requested', () => {
    const user = { username: 'alice', nickname: '小艾', avatar: '/api/users/u1/avatar' }
    expect(identityName(user)).toBe('小艾')
    const { container } = render(<UserIdentityLabel user={user} showUsername />)
    expect(screen.getByText('小艾')).toBeInTheDocument()
    expect(screen.getByText('@alice')).toBeInTheDocument()
    expect(container.querySelector('img')).toHaveAttribute('src', '/api/users/u1/avatar')
  })

  it('falls back to username and a generated placeholder', () => {
    const user = { username: 'bob', nickname: null, avatar: null }
    expect(identityName(user)).toBe('bob')
    render(<UserIdentityLabel user={user} />)
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
  })
})
