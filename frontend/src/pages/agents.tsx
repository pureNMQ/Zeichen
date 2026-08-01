import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Copy, Eye, KeyRound, Plus, Trash2, X } from 'lucide-react'
import { api, ApiError, type AgentKey, type AgentRow } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

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
  const [keys, setKeys] = useState<AgentKey[] | null>(null)
  const [showReveal, setShowReveal] = useState<string | null>(null)
  const [adminPassword, setAdminPassword] = useState('')
  const [revealed, setRevealed] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function loadKeys() {
    setKeys(await api.get<AgentKey[]>(`/agents/${agent.id}/keys`))
  }

  async function issueKey(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api.post(`/agents/${agent.id}/keys`, { note: note.trim() || null })
      setNote('')
      await loadKeys()
      await qc.invalidateQueries({ queryKey: ['agents'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '签发失败')
    }
  }

  async function doReveal(keyId: string) {
    setError(null)
    setRevealed(null)
    try {
      const res = await api.post<{ token: string }>(
        `/agents/${agent.id}/keys/${keyId}/reveal`,
        { password: adminPassword },
      )
      setRevealed(res.token)
      setAdminPassword('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '回看失败')
    }
  }

  async function revoke(keyId: string) {
    setError(null)
    await api.post(`/agents/${agent.id}/keys/${keyId}/revoke`)
    await loadKeys()
    await qc.invalidateQueries({ queryKey: ['agents'] })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) {
          setKeys(null)
          setShowReveal(null)
          setRevealed(null)
          setAdminPassword('')
          setError(null)
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>API Key 管理 · {agent.username}</DialogTitle>
          <DialogDescription>
            多 key 并存、独立吊销;回看明文需验证管理员密码
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <form onSubmit={issueKey} className="flex gap-2">
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="备注(如:桌面客户端)"
              maxLength={500}
            />
            <Button type="submit">
              <Plus className="mr-1 h-4 w-4" />
              签发
            </Button>
          </form>
          {error && <p className="text-sm text-destructive">{error}</p>}

          {keys === null && (
            <Button variant="outline" onClick={() => void loadKeys()}>
              <KeyRound className="mr-2 h-4 w-4" />
              查看已有 key
            </Button>
          )}

          {keys !== null && keys.length === 0 && (
            <p className="text-sm text-muted-foreground">暂无 key</p>
          )}

          {keys !== null && keys.length > 0 && (
            <div className="space-y-2">
              {keys.map((k) => (
                <div key={k.id} className="rounded-md border p-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">{k.note || '(无备注)'}</p>
                      <p className="text-xs text-muted-foreground">
                        签发于 {new Date(k.created_at).toLocaleString()}
                      </p>
                    </div>
                    {k.revoked_at ? (
                      <Badge variant="destructive">已吊销</Badge>
                    ) : (
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowReveal(showReveal === k.id ? null : k.id)
                            setRevealed(null)
                          }}
                        >
                          <Eye className="mr-1 h-3.5 w-3.5" />
                          回看
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void revoke(k.id)}
                        >
                          <X className="mr-1 h-3.5 w-3.5" />
                          吊销
                        </Button>
                      </div>
                    )}
                  </div>
                  {showReveal === k.id && !k.revoked_at && (
                    <div className="mt-3 space-y-2">
                      {revealed ? (
                        <RevealedToken token={revealed} />
                      ) : (
                        <div className="flex gap-2">
                          <Input
                            type="password"
                            value={adminPassword}
                            onChange={(e) => setAdminPassword(e.target.value)}
                            placeholder="输入你的管理员密码以验证"
                          />
                          <Button onClick={() => void doReveal(k.id)}>验证并显示</Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
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
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {removeError && <p className="text-sm text-destructive">{removeError}</p>}
      {!isLoading && agents?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <Bot className="h-8 w-8" />
            <p className="text-sm">暂无 Agent</p>
          </CardContent>
        </Card>
      )}

      {agents && agents.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent 列表</CardTitle>
            <CardDescription>共 {agents.length} 个</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>账号</TableHead>
                  <TableHead>项目授权</TableHead>
                  <TableHead>Key</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">{a.username}</TableCell>
                    <TableCell>
                      {a.grants.length === 0 ? (
                        <span className="text-xs text-muted-foreground">无</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {a.grants.map((g) => (
                            <Badge key={g.project_id} variant="outline">
                              {g.name} · {g.role}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.active_keys > 0 ? 'default' : 'secondary'}>
                        {a.active_keys}/{a.key_count} 有效
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setKeysFor(a)}>
                        <KeyRound className="mr-1 h-4 w-4" />
                        Key
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => void remove(a)}>
                        <Trash2 className="h-4 w-4" />
                        <span className="sr-only">删除 {a.username}</span>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <CreateAgentDialog open={createOpen} onOpenChange={setCreateOpen} />
      {keysFor && <KeyDialog agent={keysFor} open={true} onOpenChange={() => setKeysFor(null)} />}
    </div>
  )
}
