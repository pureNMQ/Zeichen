import { UserRound } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { UserIdentity } from '@/lib/api'
import { identityName } from '@/lib/user-identity'

type Identity = Pick<UserIdentity, 'username' | 'nickname' | 'display_name' | 'avatar'>

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
      ) : name ? (
        name.slice(0, 1).toUpperCase()
      ) : (
        <UserRound className="h-4 w-4" />
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
        {showUsername && name !== user.username && (
          <span className="block truncate text-xs font-normal text-muted-foreground">@{user.username}</span>
        )}
      </span>
    </span>
  )
}
