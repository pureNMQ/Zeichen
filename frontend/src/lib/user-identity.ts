import type { UserIdentity } from './api'

type Identity = Pick<UserIdentity, 'username' | 'nickname' | 'display_name' | 'avatar'>

export function identityName(user: Identity): string {
  return user.display_name || user.nickname?.trim() || user.username
}
