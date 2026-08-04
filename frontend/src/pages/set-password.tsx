import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'

export function SetPasswordPage() {
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const setupToken = params.get('token')
  const [setupUsername, setSetupUsername] = useState<string | null>(null)
  const [checkingSetupToken, setCheckingSetupToken] = useState(Boolean(setupToken))
  const [setupTokenInvalid, setSetupTokenInvalid] = useState(false)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!setupToken) return
    let cancelled = false
    void api
      .get<{ username: string }>(`/auth/password-setup?token=${encodeURIComponent(setupToken)}`)
      .then(({ username }) => {
        if (!cancelled) setSetupUsername(username)
      })
      .catch(() => {
        if (!cancelled) setSetupTokenInvalid(true)
      })
      .finally(() => {
        if (!cancelled) setCheckingSetupToken(false)
      })
    return () => {
      cancelled = true
    }
  }, [setupToken])

  if (setupTokenInvalid) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/30">
        <section className="w-full max-w-sm rounded-lg border bg-card p-8 shadow-sm">
          <h1 className="text-xl font-semibold">设密链接已失效或不存在</h1>
          <p className="mt-1 text-sm text-muted-foreground">该链接可能已被使用、已过期，或对应账号不存在。请联系管理员重新生成链接。</p>
        </section>
      </div>
    )
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError('两次输入的密码不一致')
      return
    }
    setSubmitting(true)
    try {
      if (setupToken) {
        await api.post('/auth/set-password-with-token', { password, token: setupToken })
      } else {
        await api.post('/auth/set-password', { password })
      }
      await refresh()
      navigate('/projects', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '设置密码失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-lg border bg-card p-8 shadow-sm"
      >
        <h1 className="text-xl font-semibold">设置密码</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {setupToken
            ? checkingSetupToken
              ? '正在验证设密链接…'
              : `为账号 ${setupUsername} 设置首次密码`
            : `欢迎${params.get('user') ? `,${params.get('user')}` : ''} · 首次登录请设置你的密码`}
        </p>
        <div className="mt-6 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="password">新密码(至少 8 位)</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm">确认密码</Label>
            <Input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          <ErrorNotification message={error} />
          <Button type="submit" className="w-full" disabled={submitting || checkingSetupToken || (setupToken !== null && setupUsername === null)}>
            {submitting ? '保存中…' : '保存并进入'}
          </Button>
        </div>
      </form>
    </div>
  )
}
