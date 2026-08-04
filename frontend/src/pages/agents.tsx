import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Copy, Eye, KeyRound, Plus, Trash2, X } from 'lucide-react'
import { api, ApiError, type AgentKey, type AgentRow } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

function CreateAgentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.post('/agents', { username: username.trim(), project_grants: [] })
      setUsername('')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['agents'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建 Agent</DialogTitle>
          <DialogDescription>Agent 凭 API key 经 MCP 访问,不设密码</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="agent-username">Agent 账号名</Label>
            <Input
              id="agent-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              maxLength={64}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RevealedToken({ token }: { token: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex items-center gap-2 rounded-md bg-muted p-2">
      <code className="min-w-0 flex-1 break-all text-xs">{token}</code>
      <Button
        variant="ghost"
        size="sm"
        onClick={async () => {
          await navigator.clipboard.writeText(token)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
      >
        <Copy className="mr-1 h-3.5 w-3.5" />
        {copied ? '已复制' : '复制'}
      </Button>
    </div>
  )
}

type IssuedKey = {
  id: string
  token: string
}

function KeyDialog({
  agent,
  open,
  onOpenChange,
}: {
  agent: AgentRow
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [keys, setKeys] = useState<AgentKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [revealed, setRevealed] = useState<IssuedKey | null>(null)
  const [revealFor, setRevealFor] = useState<AgentKey | null>(null)
  const [adminPassword, setAdminPassword] = useState('')
  const [revealError, setRevealError] = useState<string | null>(null)

  const loadKeys = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await api.get<AgentKey[]>(`/agents/${agent.id}/keys`)
      setKeys(rows.filter((key) => key.revoked_at === null))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载 Key 失败')
    } finally {
      setLoading(false)
    }
  }, [agent.id])

  useEffect(() => {
    if (open) void loadKeys()
  }, [open, loadKeys])

  async function issueKey(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      const issued = await api.post<IssuedKey>(`/agents/${agent.id}/keys`, {
        note: note.trim() || null,
      })
      setNote('')
      await loadKeys()
      setRevealed(issued)
      await qc.invalidateQueries({ queryKey: ['agents'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '签发失败')
    }
  }

  async function revoke(keyId: string) {
    setError(null)
    try {
      await api.post(`/agents/${agent.id}/keys/${keyId}/revoke`)
      setKeys((current) => current.filter((key) => key.id !== keyId))
      setRevealed((current) => (current?.id === keyId ? null : current))
      await qc.invalidateQueries({ queryKey: ['agents'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '吊销失败')
    }
  }

  async function revealKey(e: FormEvent) {
    e.preventDefault()
    if (!revealFor) return
    setRevealError(null)
    try {
      const result = await api.post<{ token: string }>(
        `/agents/${agent.id}/keys/${revealFor.id}/reveal`,
        { password: adminPassword },
      )
      setRevealed({ id: revealFor.id, token: result.token })
      setAdminPassword('')
      setRevealFor(null)
    } catch (err) {
      setRevealError(err instanceof ApiError ? err.message : '回看失败')
    }
  }

  function closeRevealDialog(opened: boolean) {
    if (!opened) {
      setRevealFor(null)
      setAdminPassword('')
      setRevealError(null)
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>API Key 管理 · {agent.username}</DialogTitle>
            <DialogDescription>打开即加载全部有效 Key；回看明文需验证管理员密码。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <form onSubmit={issueKey} className="flex gap-2">
              <Input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                autoComplete="off"
                placeholder="备注（如：桌面客户端）"
                maxLength={500}
              />
              <Button type="submit">
                <Plus className="mr-1 h-4 w-4" />
                签发
              </Button>
            </form>
            {error && <p className="text-sm text-destructive">{error}</p>}

            {loading && <p className="text-sm text-muted-foreground">正在加载 Key…</p>}
            {!loading && keys.length === 0 && (
              <p className="text-sm text-muted-foreground">暂无有效 Key</p>
            )}
            {!loading && keys.length > 0 && (
              <div className="space-y-2" aria-label="有效 Key 列表">
                {keys.map((key) => (
                  <div key={key.id} className="rounded-md border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{key.note || '（无备注）'}</p>
                        <p className="text-xs text-muted-foreground">
                          签发于 {new Date(key.created_at).toLocaleString()}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => setRevealFor(key)}
                          aria-label={`回看 ${key.note || 'API Key'}`}
                          title="回看"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => void revoke(key.id)}
                          aria-label={`吊销 ${key.note || 'API Key'}`}
                          title="吊销"
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    {revealed?.id === key.id && (
                      <div className="mt-3">
                        <RevealedToken token={revealed.token} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={revealFor !== null} onOpenChange={closeRevealDialog}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>验证管理员密码</DialogTitle>
            <DialogDescription>验证通过后将显示该 API Key 的明文。</DialogDescription>
          </DialogHeader>
          <form onSubmit={revealKey} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="key-reveal-password">当前密码</Label>
              <Input
                id="key-reveal-password"
                type="password"
                value={adminPassword}
                onChange={(e) => setAdminPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {revealError && <p className="text-sm text-destructive">{revealError}</p>}
            <DialogFooter>
              <Button type="submit">验证并显示</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function AgentsPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const [keysFor, setKeysFor] = useState<AgentRow | null>(null)
  const {
    data: agents,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['agents'],
    queryFn: () => api.get<AgentRow[]>('/agents'),
  })
  const qc = useQueryClient()
  const [removeError, setRemoveError] = useState<string | null>(null)

  async function remove(agent: AgentRow) {
    if (!window.confirm(`删除 Agent ${agent.username}?其全部 key 将吊销、授权将清除`)) return
    setRemoveError(null)
    try {
      await api.delete(`/agents/${agent.id}`)
      await qc.invalidateQueries({ queryKey: ['agents'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Agent 管理</h1>
          <p className="text-sm text-muted-foreground">凭 API key 经 MCP 访问的账号,管理员专属</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          创建 Agent
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      <ErrorNotification message={removeError} />
      {!isLoading && agents?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <Bot className="h-8 w-8" />
            <p className="text-sm">暂无 Agent</p>
          </CardContent>
        </Card>
      )}

      {agents && agents.length > 0 && (
        <section className="space-y-3" aria-labelledby="agents-list-title">
          <div>
            <h2 id="agents-list-title" className="text-base font-medium">Agent 列表</h2>
            <p className="text-sm text-muted-foreground">共 {agents.length} 个</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {agents.map((a) => (
              <Card key={a.id} data-testid="agent-card" className="h-64 overflow-hidden">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Bot className="h-4 w-4 text-muted-foreground" />
                    {a.username}
                  </CardTitle>
                  <CardDescription>创建于 {new Date(a.created_at).toLocaleDateString()}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">项目授权</p>
                    {a.grants.length === 0 ? (
                      <p className="text-sm text-muted-foreground">暂无项目授权</p>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {a.grants.map((g) => (
                          <Badge key={g.project_id} variant="outline">
                            {g.name} · {g.role}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">API Key</p>
                    <Badge variant={a.active_keys > 0 ? 'default' : 'secondary'}>
                      {a.active_keys}/{a.key_count} 有效
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2 border-t pt-3">
                    <Button variant="outline" size="sm" className="flex-1" onClick={() => setKeysFor(a)}>
                      <KeyRound className="h-4 w-4" />
                      管理 Key
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => void remove(a)}
                      aria-label={`删除 ${a.username}`}
                      title={`删除 ${a.username}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      <CreateAgentDialog open={createOpen} onOpenChange={setCreateOpen} />
      {keysFor && <KeyDialog agent={keysFor} open={true} onOpenChange={() => setKeysFor(null)} />}
    </div>
  )
}
