import { useEffect, useState, type FormEvent } from 'react'

import { api, ApiError, type UserIdentity } from '@/lib/api'
import { UserAvatar } from '@/components/user-avatar'
import { identityName } from '@/lib/user-identity'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export function UserProfileDialog({
  user,
  open,
  onOpenChange,
  onSaved,
  self = false,
}: {
  user: UserIdentity
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void | Promise<void>
  self?: boolean
}) {
  const [nickname, setNickname] = useState(user.nickname ?? '')
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const basePath = self ? '/users/me' : `/users/${user.id}`

  useEffect(() => {
    if (open) {
      setNickname(user.nickname ?? '')
      setAvatarFile(null)
      setError(null)
    }
  }, [open, user.nickname])

  async function save(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await api.patch(basePath, { nickname: nickname.trim() || null })
      if (avatarFile) {
        const form = new FormData()
        form.append('file', avatarFile)
        await api.upload(`${basePath}/avatar`, form)
      }
      await onSaved()
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存资料失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function removeAvatar() {
    setSubmitting(true)
    setError(null)
    try {
      await api.delete(`${basePath}/avatar`)
      setAvatarFile(null)
      await onSaved()
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '移除头像失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{self ? '个人资料' : `编辑 ${identityName(user)} 的资料`}</DialogTitle>
          <DialogDescription>登录账号 @{user.username} 不会随昵称修改。</DialogDescription>
        </DialogHeader>
        <form onSubmit={save} className="space-y-4">
          <div className="flex items-center gap-4">
            <UserAvatar user={user} className="h-16 w-16 text-lg" />
            <div className="space-y-2">
              <Label htmlFor={`avatar-${user.id}`}>头像</Label>
              <Input
                id={`avatar-${user.id}`}
                type="file"
                accept="image/jpeg,image/png,image/gif,image/webp"
                autoComplete="off"
                onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)}
              />
              <p className="text-xs text-muted-foreground">JPEG、PNG、GIF 或 WebP，不超过 20MB</p>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`nickname-${user.id}`}>昵称</Label>
            <Input
              id={`nickname-${user.id}`}
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              autoComplete="nickname"
              maxLength={64}
              placeholder={user.username}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter className="sm:justify-between">
            <Button type="button" variant="outline" disabled={submitting || !user.avatar} onClick={() => void removeAvatar()}>
              移除头像
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? '保存中…' : '保存资料'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
