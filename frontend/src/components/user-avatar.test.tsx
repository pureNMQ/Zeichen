import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UserIdentityLabel, MemberAccountLabel } from './user-avatar'
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

  it('falls back to a deterministic beam avatar generated from the user id', () => {
    const user = { id: 'user-42', username: 'bob', nickname: null, avatar: null }
    expect(identityName(user)).toBe('bob')
    const { container } = render(<UserIdentityLabel user={user} />)
    expect(screen.getByText('bob')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
    expect(screen.queryByText('B')).not.toBeInTheDocument()
  })

  it('keeps the @account line rendered at equal height even without a nickname', () => {
    const noNickname = { id: 'user-7', username: 'bob', nickname: null, avatar: null }
    const { rerender } = render(<UserIdentityLabel user={noNickname} showUsername />)
    const placeholder = screen.getByText('@bob')
    expect(placeholder).toHaveClass('invisible')
    expect(placeholder).toHaveAttribute('aria-hidden', 'true')

    rerender(<UserIdentityLabel user={{ username: 'alice', nickname: '小艾', avatar: null }} showUsername />)
    expect(screen.getByText('@alice')).not.toHaveClass('invisible')
    expect(screen.getByText('@alice')).not.toHaveAttribute('aria-hidden', 'true')
  })

  it('agent 徽标与身份标签在同一垂直居中弹性行内', () => {
    const agent = { id: 'user-9', username: 'Maintainer', nickname: null, avatar: null }
    const { container } = render(<MemberAccountLabel user={agent} isAgent />)
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper).toHaveClass('inline-flex')
    expect(wrapper).toHaveClass('items-center')
    const iconSpan = wrapper.querySelector('span[title="Agent"]')
    expect(iconSpan).not.toBeNull()
    expect(iconSpan).toHaveClass('shrink-0')
    expect(wrapper.querySelector('svg')).not.toBeNull()
  })

  it('人类成员不渲染 agent 徽标', () => {
    const human = { id: 'user-1', username: 'alice', nickname: null, avatar: null }
    const { container } = render(<MemberAccountLabel user={human} isAgent={false} />)
    expect(container.querySelector('span[title="Agent"]')).toBeNull()
  })
})
