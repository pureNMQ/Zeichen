import Avatar from 'boring-avatars'
import { Bot } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { UserIdentity } from '@/lib/api'
import { identityName } from '@/lib/user-identity'

type Identity = Pick<UserIdentity, 'username' | 'nickname' | 'display_name' | 'avatar'> & {
  id?: string | null
}

const DEFAULT_AVATAR_COLORS = ['#ffefd3', '#fffee4', '#d0ecea', '#9fd6d2', '#8b7a5e']

export function UserAvatar({ user, className }: { user: Identity; className?: string }) {
  const name = identityName(user)
  return (
    <span
      className={cn('inline-flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-medium text-muted-foreground', className)}
      title={name}
      aria-label={`${name} 的头像`}
    >
      {user.avatar ? (
        <img src={user.avatar} alt="" className="h-full w-full object-cover" />
      ) : (
        <Avatar
          name={`zeichen:user:${user.id ?? user.username}`}
          variant="beam"
          colors={DEFAULT_AVATAR_COLORS}
          size="100%"
          aria-hidden="true"
          focusable="false"
        />
      )}
    </span>
  )
}

export function UserIdentityLabel({ user, showUsername = false }: { user: Identity; showUsername?: boolean }) {
  const name = identityName(user)
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <UserAvatar user={user} />
      <span className="min-w-0">
        <span className="block truncate">{name}</span>
        {showUsername && (
          <span
            className={cn('block truncate text-xs font-normal text-muted-foreground', name === user.username && 'invisible')}
            aria-hidden={name === user.username || undefined}
          >
            @{user.username}
          </span>
        )}
      </span>
    </span>
  )
}

export function MemberAccountLabel({ user, isAgent }: { user: Identity; isAgent: boolean }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <UserIdentityLabel user={user} showUsername />
      {isAgent && (
        <span className="inline-flex shrink-0" title="Agent">
          <Bot className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          <span className="sr-only">Agent</span>
        </span>
      )}
    </span>
  )
}
