import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { authReturnPath } from '@/lib/auth-return'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'

export function SetPasswordPage() {
  const { refresh } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const setupToken = params.get('token')
  const setup = useQuery({
    queryKey: ['password-setup', setupToken],
    queryFn: ({ signal }) => api.get<{ username: string }>(`/auth/password-setup?token=${encodeURIComponent(setupToken!)}`, signal),
    enabled: Boolean(setupToken),
    retry: false,
    gcTime: 0,
  })
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (setupToken && setup.isError) {
    const invalid = setup.error instanceof ApiError && [401, 404, 422].includes(setup.error.status)
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/30">
        <section className="w-full max-w-sm space-y-3 rounded-lg border bg-card p-8 shadow-sm">
          <h1 className="text-xl font-semibold">{invalid ? '设密链接已失效或不存在' : '设置密码'}</h1>
          {invalid ? <p className="text-sm text-muted-foreground">请联系管理员重新生成设密链接。</p> : <>
            <ErrorNotification message="暂时无法验证设密链接，请重试。" />
            <Button disabled={setup.isFetching} onClick={() => void setup.refetch()}>
              {setup.isFetching ? '验证中…' : '重试验证'}
            </Button>
          </>}
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
      navigate(authReturnPath(params.get('from')), { replace: true })
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
            ? setup.isLoading
              ? '正在验证设密链接…'
              : `为账号 ${setup.data?.username} 设置首次密码`
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
          <Button type="submit" className="w-full" disabled={submitting || (!!setupToken && !setup.data)}>
            {submitting ? '保存中…' : '保存并进入'}
          </Button>
        </div>
      </form>
    </div>
  )
}
