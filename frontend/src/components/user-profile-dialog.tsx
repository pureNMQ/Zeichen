import { useEffect, useState, type FormEvent } from 'react'

import { api, ApiError, type UserIdentity } from '@/lib/api'
import { UserAvatar } from '@/components/user-avatar'
import { identityName } from '@/lib/user-identity'
import { ErrorNotification } from '@/components/ui/notification'
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
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null)
  const [restoreDefaultAvatar, setRestoreDefaultAvatar] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const basePath = self ? '/users/me' : `/users/${user.id}`

  useEffect(() => {
    if (open) {
      setNickname(user.nickname ?? '')
      setAvatarFile(null)
      setAvatarPreview(null)
      setRestoreDefaultAvatar(false)
      setError(null)
    }
  }, [open, user.nickname])

  useEffect(() => () => {
    if (avatarPreview) URL.revokeObjectURL(avatarPreview)
  }, [avatarPreview])

  function selectAvatar(file: File | null) {
    setAvatarFile(file)
    setRestoreDefaultAvatar(false)
    setAvatarPreview((current) => {
      if (current) URL.revokeObjectURL(current)
      return file ? URL.createObjectURL(file) : null
    })
  }

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
      } else if (restoreDefaultAvatar) {
        await api.delete(`${basePath}/avatar`)
      }
      await onSaved()
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存资料失败')
    } finally {
      setSubmitting(false)
    }
  }

  function previewDefaultAvatar() {
    selectAvatar(null)
    setRestoreDefaultAvatar(true)
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
            <UserAvatar user={{ ...user, avatar: restoreDefaultAvatar ? null : avatarPreview ?? user.avatar }} className="h-16 w-16 text-lg" />
            <div className="space-y-2">
              <Label htmlFor={`avatar-${user.id}`}>头像</Label>
              <div className="flex items-center gap-2">
                <Input
                  id={`avatar-${user.id}`}
                  type="file"
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  autoComplete="off"
                  onChange={(event) => selectAvatar(event.target.files?.[0] ?? null)}
                />
                <Button type="button" variant="outline" disabled={submitting || (!user.avatar && !avatarFile)} onClick={previewDefaultAvatar}>
                  恢复默认头像
                </Button>
              </div>
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
          <ErrorNotification message={error} />
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '保存中…' : '保存资料'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
