import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, ExternalLink, Sparkles, Trash2 } from 'lucide-react'
import { Link, NavLink, Navigate } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorNotification, useNotification } from '@/components/ui/notification'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, ApiError, type MemoryImproveJob, type MemoryItem, type MemorySession, type MemorySessionDetail } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { cn } from '@/lib/utils'

type MemoryResponse = { items: MemoryItem[] }
const EMPTY_MEMORIES: MemoryItem[] = []
const EMPTY_SESSIONS: MemorySession[] = []

function displayMemory(item: MemoryItem) {
  return item.content ?? item.data ?? item.text ?? '（内容不可用）'
}

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString() : '时间未知'
}

function sessionIdOf(session: MemorySession) {
  return session.session_id ?? session.id ?? ''
}

function parseSession(projectId: string, session: MemorySession) {
  const raw = sessionIdOf(session)
  const prefix = `zeichen:${projectId}:`
  if (!raw.startsWith(prefix)) return null
  const [, , agentId, ...parts] = raw.split(':')
  const businessSessionId = parts.join(':')
  return agentId && businessSessionId ? { agentId, businessSessionId, raw } : null
}

function anchorHref(item: MemoryItem) {
  const metadata = item.external_metadata
  if (!metadata?.entity_id) return null
  if (metadata.entity_type === 'task') return `/tasks/${metadata.entity_id}`
  if (metadata.entity_type === 'requirement') return `/requirements/${metadata.entity_id}`
  return null
}

function AnchorLabel({ item }: { item: MemoryItem }) {
  const metadata = item.external_metadata
  if (!metadata?.entity_type || !metadata.entity_id) return <span>未关联业务实体</span>
  const label = `${metadata.entity_type} / ${metadata.entity_id}`
  const href = anchorHref(item)
  if (!href) return <span>{label}</span>
  return <Link to={href} className="inline-flex items-center gap-1 hover:underline" onClick={(event) => event.stopPropagation()}>{label}<ExternalLink className="h-3 w-3" /></Link>
}

function NoProjectGuide() {
  return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">请先在侧边栏选择项目</CardContent></Card>
}

function MemoryShell({ children }: { children: (projectId: string) => ReactNode }) {
  const { projectId, currentProject, isLoading: projectLoading } = useCurrentProject()
  const role = useProjectRole()

  if (projectLoading) return null
  if (!currentProject || !projectId) return <NoProjectGuide />
  if (role !== 'editor' && role !== 'owner') return <Navigate to="/requirements" replace />

  const tabClass = ({ isActive }: { isActive: boolean }) => cn(
    'border-b-2 px-1 pb-2 text-sm font-medium transition-colors',
    isActive ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
  )

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">记忆</h1>
        <p className="mt-1 text-sm text-muted-foreground">{currentProject.name}</p>
      </div>
      <nav className="flex gap-5 border-b" aria-label="记忆导航">
        <NavLink to="/memory" end className={tabClass}>长期记忆</NavLink>
        <NavLink to="/memory/sessions" className={tabClass}>会话缓存</NavLink>
      </nav>
      {children(projectId)}
    </div>
  )
}

function DetailDialog({ open, onOpenChange, title, description, children }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[min(42rem,calc(100dvh-2rem))] gap-5 overflow-hidden p-5 sm:max-w-2xl">
        <DialogHeader className="pr-8">
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  )
}

function LongTermMemories({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [source, setSource] = useState('all')
  const [selected, setSelected] = useState<MemoryItem | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const memoryQuery = useQuery({
    queryKey: ['memory', projectId],
    queryFn: () => api.get<MemoryResponse>(`/projects/${projectId}/memory`),
  })
  const memories = memoryQuery.data?.items ?? EMPTY_MEMORIES
  const sources = useMemo(() => {
    const values = new Map<string, string>()
    memories.forEach((item) => {
      const metadata = item.external_metadata
      if (metadata?.source_id) values.set(metadata.source_id, metadata.source_name ?? metadata.source_id)
    })
    return [...values.entries()]
  }, [memories])
  const visibleMemories = source === 'all' ? memories : memories.filter((item) => item.external_metadata?.source_id === source)

  async function forget() {
    if (!selected) return
    setActionError(null)
    try {
      await api.delete(`/projects/${projectId}/memory/${selected.id}`)
      setDeleteOpen(false)
      setSelected(null)
      await queryClient.invalidateQueries({ queryKey: ['memory', projectId] })
    } catch (error) {
      setDeleteOpen(false)
      setActionError(error instanceof ApiError ? error.message : '删除记忆失败')
    }
  }

  return (
    <section className="space-y-4">
      <div className="max-w-sm space-y-1.5">
        <Label htmlFor="memory-source">来源</Label>
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger id="memory-source"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部来源</SelectItem>
            {sources.map(([id, name]) => <SelectItem key={id} value={id}>{name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <ErrorNotification message={memoryQuery.error ? (memoryQuery.error as Error).message : null} />
      <ErrorNotification message={actionError} />
      {memoryQuery.isLoading && <p className="text-sm text-muted-foreground">正在加载长期记忆…</p>}
      {!memoryQuery.isLoading && !memoryQuery.error && memories.length === 0 && (
        <Card><CardContent className="space-y-3 py-12 text-center">
          <p className="text-sm text-muted-foreground">还没有长期记忆。请从会话缓存中选择一个会话进行蒸馏。</p>
          <Button asChild variant="outline"><Link to="/memory/sessions">前往会话缓存</Link></Button>
        </CardContent></Card>
      )}
      {!memoryQuery.isLoading && !memoryQuery.error && memories.length > 0 && visibleMemories.length === 0 && <p className="py-10 text-center text-sm text-muted-foreground">没有符合筛选条件的长期记忆。</p>}
      <div className="divide-y rounded-lg border">
        {visibleMemories.map((item) => {
          const metadata = item.external_metadata
          return (
            <div key={item.id} role="button" tabIndex={0} aria-label={`查看记忆详情 ${item.id}`} className="grid w-full cursor-pointer gap-2 p-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[minmax(0,1fr)_11rem]" onClick={() => setSelected(item)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(item) } }}>
              <div className="min-w-0"><p className="truncate text-sm font-medium">{displayMemory(item)}</p><p className="mt-1 text-xs text-muted-foreground">锚点：<AnchorLabel item={item} /></p></div>
              <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground sm:block sm:text-right"><span>{metadata?.source_name ?? '未知来源'}</span><span className="sm:mt-1 sm:block">{formatTime(item.created_at)}</span></div>
            </div>
          )
        })}
      </div>
      <DetailDialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)} title="记忆详情" description={selected ? `${selected.external_metadata?.source_name ?? '未知来源'} · ${formatTime(selected.created_at)}` : undefined}>
        {selected && <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto">
          <div className="space-y-2"><h3 className="text-sm font-medium">内容</h3><p className="whitespace-pre-wrap text-sm leading-6">{displayMemory(selected)}</p></div>
          <div className="space-y-2"><h3 className="text-sm font-medium">业务锚点</h3><p className="text-sm text-muted-foreground"><AnchorLabel item={selected} /></p></div>
          <div className="mt-auto border-t pt-4"><Button variant="destructive" size="sm" onClick={() => setDeleteOpen(true)}><Trash2 className="mr-1 h-3.5 w-3.5" />删除记忆</Button></div>
        </div>}
      </DetailDialog>
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>删除这条记忆？</DialogTitle><DialogDescription>此操作不可恢复，确定后将从项目共享记忆中永久移除。</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void forget()}>确认删除</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function CachedSessions({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const notify = useNotification()
  const [agent, setAgent] = useState('all')
  const [status, setStatus] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [isImproving, setIsImproving] = useState(false)
  const [improveJobId, setImproveJobId] = useState<string | null>(null)
  const [notifiedCompletedJobId, setNotifiedCompletedJobId] = useState<string | null>(null)
  const sessionQuery = useQuery({
    queryKey: ['memory-sessions', projectId],
    queryFn: () => api.get<{ items: MemorySession[] }>(`/projects/${projectId}/memory/sessions`),
  })
  const sessions = (sessionQuery.data?.items ?? EMPTY_SESSIONS)
    .map((item) => {
      const parsed = parseSession(projectId, item)
      return parsed ? { ...item, ...parsed, sourceName: item.source_name ?? `Agent ${parsed.agentId.slice(0, 8)}`, status: item.effective_status ?? item.status ?? '未知状态' } : null
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
  const agents = useMemo(() => [...new Map(sessions.map((item) => [item.agentId, item.sourceName])).entries()], [sessions])
  const statuses = useMemo(() => [...new Set(sessions.map((item) => item.status).filter((value) => value !== 'all'))], [sessions])
  const visibleSessions = sessions.filter((item) => (agent === 'all' || item.agentId === agent) && (status === 'all' || item.status === status))
  const selected = sessions.find((item) => item.raw === selectedId) ?? null
  const detailQuery = useQuery({
    queryKey: ['memory-session-detail', projectId, selectedId],
    queryFn: () => api.get<MemorySessionDetail>(`/projects/${projectId}/memory/sessions/${encodeURIComponent(selectedId ?? '')}`),
    enabled: !!selectedId,
  })
  const improveJobQuery = useQuery({
    queryKey: ['memory-improve-job', projectId, improveJobId],
    queryFn: () => api.get<{ job: MemoryImproveJob }>(`/projects/${projectId}/memory/improve-jobs/${improveJobId}`),
    enabled: !!improveJobId,
    refetchInterval: (query) => {
      const status = query.state.data?.job.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
  })
  const improveJob = improveJobQuery.data?.job

  useEffect(() => {
    if (improveJob?.status !== 'completed' || notifiedCompletedJobId === improveJob.id) return
    setNotifiedCompletedJobId(improveJob.id)
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['memory-sessions', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['memory', projectId] }),
    ])
    notify('会话已蒸馏为长期记忆。', 'success')
  }, [improveJob, notifiedCompletedJobId, notify, projectId, queryClient])

  async function improve() {
    if (!selected) return
    setActionError(null)
    setIsImproving(true)
    try {
      const response = await api.post<{ job: MemoryImproveJob }>(`/projects/${projectId}/memory/improve`, { agent_id: selected.agentId, session_id: selected.businessSessionId })
      setImproveJobId(response.job.id)
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : '蒸馏记忆失败')
    } finally {
      setIsImproving(false)
    }
  }

  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="session-agent">Agent</Label><Select value={agent} onValueChange={setAgent}><SelectTrigger id="session-agent"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部 Agent</SelectItem>{agents.map(([id, name]) => <SelectItem key={id} value={id}>{name}</SelectItem>)}</SelectContent></Select></div>
        <div className="space-y-1.5"><Label htmlFor="session-status">状态</Label><Select value={status} onValueChange={setStatus}><SelectTrigger id="session-status"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部状态</SelectItem>{statuses.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></div>
      </div>
      <ErrorNotification message={sessionQuery.error ? (sessionQuery.error as Error).message : null} />
      <ErrorNotification message={actionError} />
      <ErrorNotification message={improveJob?.status === 'completed' ? null : improveJob?.error} />
      {sessionQuery.isLoading && <p className="text-sm text-muted-foreground">正在加载会话缓存…</p>}
      {!sessionQuery.isLoading && !sessionQuery.error && sessions.length === 0 && <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">当前项目没有可查看的会话缓存。</CardContent></Card>}
      {!sessionQuery.isLoading && !sessionQuery.error && sessions.length > 0 && visibleSessions.length === 0 && <p className="py-10 text-center text-sm text-muted-foreground">没有符合筛选条件的会话缓存。</p>}
      <div className="divide-y rounded-lg border">
        {visibleSessions.map((item) => <div key={item.raw} role="button" tabIndex={0} aria-label={`查看会话缓存 ${item.businessSessionId}`} className="grid w-full cursor-pointer gap-2 p-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[minmax(0,1fr)_11rem]" onClick={() => setSelectedId(item.raw)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(item.raw) } }}>
          <div className="min-w-0"><p className="truncate text-sm font-medium">{item.businessSessionId}</p><p className="mt-1 truncate text-xs text-muted-foreground">{item.preview ?? '暂无可显示的问答摘要'}</p></div>
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground sm:block sm:text-right"><Badge variant="outline">{item.status}</Badge><span className="sm:mt-1 sm:block">{item.sourceName} · {formatTime(item.last_activity_at)}</span></div>
        </div>)}
      </div>
      <DetailDialog open={selected !== null} onOpenChange={(open) => !open && setSelectedId(null)} title={selected?.businessSessionId ?? '会话缓存'} description={selected ? `${selected.sourceName} · ${selected.status}` : undefined}>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
          <ErrorNotification message={detailQuery.error ? (detailQuery.error as Error).message : null} />
          {detailQuery.isLoading && <p className="text-sm text-muted-foreground">正在加载会话内容…</p>}
          {!detailQuery.isLoading && !detailQuery.error && (detailQuery.data?.qas.length ?? 0) === 0 && <p className="text-sm text-muted-foreground">此会话暂无可展示的问答缓存。</p>}
          {detailQuery.data?.qas.map((qa, index) => <Card key={`${qa.time ?? 'qa'}-${index}`}><CardContent className="space-y-2 py-4 text-sm"><p className="font-medium">问：{qa.question ?? '（问题不可用）'}</p><p className="whitespace-pre-wrap text-muted-foreground">答：{qa.answer ?? '（回答不可用）'}</p>{qa.time && <p className="text-xs text-muted-foreground">{formatTime(qa.time)}</p>}</CardContent></Card>)}
          {improveJob && <Card><CardContent className="flex items-center justify-between gap-3 py-3 text-sm"><span>蒸馏任务</span><Badge variant="outline">{improveJob.status}</Badge></CardContent></Card>}
          <div className="mt-auto border-t pt-4"><Button onClick={() => void improve()} disabled={isImproving || detailQuery.isLoading || improveJob?.status === 'queued' || improveJob?.status === 'running'}><Sparkles className="mr-1 h-3.5 w-3.5" />{isImproving ? '正在提交…' : improveJob?.status === 'queued' || improveJob?.status === 'running' ? '蒸馏任务进行中' : '蒸馏为长期记忆'}<ChevronRight className="ml-1 h-3.5 w-3.5" /></Button></div>
        </div>
      </DetailDialog>
    </section>
  )
}

export function MemoryPage() {
  return <MemoryShell>{(projectId) => <LongTermMemories projectId={projectId} />}</MemoryShell>
}

export function MemorySessionsPage() {
  return <MemoryShell>{(projectId) => <CachedSessions projectId={projectId} />}</MemoryShell>
}
