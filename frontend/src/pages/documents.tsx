import { useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { ArrowUpToLine, Bot, ChevronDown, ChevronRight, History, Link2, ListTree, MoreHorizontal, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { MarkdownComposer } from '@/components/markdown-composer'
import { useProjectCompletion } from '@/lib/project-completion'
import { projectFileUpload } from '@/lib/project-files'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { AttachmentList } from '@/components/attachment-list'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ErrorNotification } from '@/components/ui/notification'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, ApiError, type AuthorIdentity, type DocumentNode, type DocumentRow, type DocumentType, type DocumentVersionRow, type WikiIndex, type WikiLinks, withProject } from '@/lib/api'
import { filterNodesByTitle } from '@/lib/document-search'
import { planDocumentMove, rootZoneFirstPointerWithin } from '@/lib/document-tree-dnd'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { useDocumentNavigation } from '@/lib/document-navigation'
import { projectResourceHref } from '@/lib/project-links'
// REQ-59 Q2④:九形态约定值(与后端 DOC_KINDS 对齐;未分类兜底)
const DOC_KIND_LABELS: Record<string, string> = {
  decision: '决策', incident: '事故', preference: '偏好', concept: '概念',
  entity: '实体', comparison: '对比', research: '调研', howto: '操作指南', spec: '规格',
}

function kindLabel(kind: string | null | undefined) {
  if (!kind) return '未分类'
  return DOC_KIND_LABELS[kind] ?? kind
}

function authorDisplayName(author: AuthorIdentity | null | undefined): string {
  if (!author) return '未知'
  const name = author.nickname || author.username
  if (author.is_agent && author.owner) {
    const owner = author.owner.nickname || author.owner.username
    return `${name}(${owner} 的 agent)`
  }
  return name
}

function AuthorBadge({ author, compact }: { author: AuthorIdentity | null | undefined; compact?: boolean }) {
  if (!author) return <span className="text-muted-foreground">未知</span>
  const name = author.nickname || author.username
  return <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" data-testid="author-badge" title={authorDisplayName(author)}>
    {author.is_agent && <Bot className="h-3.5 w-3.5" aria-label="agent" />}
    {author.is_agent && author.owner ? <span>{name} · 主人 {author.owner.nickname || author.owner.username}</span> : <span>{name}</span>}
    {!compact && <span className="text-muted-foreground/70">·</span>}
    {!compact && <span>更新者溯源</span>}
  </span>
}

function moduleBase(projectId?: string) {
  return projectId ? projectResourceHref(projectId, 'wiki') : '/documents/wiki'
}

function documentUrl(id: string, projectId?: string) {
  return `${moduleBase(projectId)}/${encodeURIComponent(id)}`
}

function parseNodeFromRoute(id: string | undefined) {
  if (!id) return null
  return { id, kind: 'document' as const }
}

function NoProject() {
  return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">请先在侧边栏选择当前项目。</CardContent></Card>
}

function treeKey(projectId: string, parentId: string | null) {
  return ['document-tree', projectId, parentId]
}

function TreeChildren({ projectId, parentId, filter, expanded, onToggle, onNavigate, selectedId, canEdit, onMoveToRoot, onRename, onDelete }: {
  projectId: string
  parentId: string | null
  filter: string
  expanded: Set<string>
  onToggle: (id: string) => void
  onNavigate: (url: string) => void
  selectedId?: string
  canEdit: boolean
  onMoveToRoot: (node: DocumentNode) => void
  onRename: (node: DocumentNode) => void
  onDelete: (node: DocumentNode) => void
}) {
  const { data } = useQuery({ queryKey: treeKey(projectId, parentId), queryFn: () => api.get<{ items: DocumentNode[]; next_cursor: string | null }>(`/projects/${projectId}/documents/wiki/children?${parentId ? `parent_id=${parentId}&` : ''}limit=100`) })
  const nodes = filterNodesByTitle(data?.items ?? [], filter)
  return <>{nodes.map((node) => {
    const open = expanded.has(node.id)
    return <TreeRow key={node.id} node={node} dragEnabled={canEdit} canDrag={canEdit} open={open} selectedId={selectedId} onToggle={onToggle} onNavigate={onNavigate} onRename={onRename} onDelete={onDelete} onMoveToRoot={onMoveToRoot} atRoot={!parentId}>
      {node.has_children && open && <TreeChildren projectId={projectId} parentId={node.id} filter={filter} expanded={expanded} onToggle={onToggle} onNavigate={onNavigate} selectedId={selectedId} canEdit={canEdit} onMoveToRoot={onMoveToRoot} onRename={onRename} onDelete={onDelete} />}
    </TreeRow>
  })}</>
}

function TreeRow({ node, dragEnabled, canDrag, open, selectedId, onToggle, onNavigate, onRename, onDelete, onMoveToRoot, atRoot, children }: {
  node: DocumentNode
  dragEnabled: boolean
  canDrag: boolean
  open: boolean
  selectedId?: string
  onToggle: (id: string) => void
  onNavigate: (url: string) => void
  onRename: (node: DocumentNode) => void
  onDelete: (node: DocumentNode) => void
  onMoveToRoot?: (node: DocumentNode) => void
  atRoot?: boolean
  children?: ReactNode
}) {
  const { routeProjectId } = useCurrentProject()
  const drag = useDraggable({ id: `drag:document:${node.id}`, data: { kind: 'document', id: node.id }, disabled: !dragEnabled, attributes: { role: 'presentation' } })
  const drop = useDroppable({ id: `drop:document:${node.id}`, data: { kind: 'document', id: node.id } })
  return <div>
      <div
        ref={(el) => { drag.setNodeRef(el); drop.setNodeRef(el) }}
        {...drag.attributes}
        {...drag.listeners}
        style={drag.transform ? { transform: `translate3d(${drag.transform.x}px, ${drag.transform.y}px, 0)` } : undefined}
        className={`group flex min-w-0 touch-none items-center gap-1 rounded-md pr-1 ${drop.isOver ? 'ring-2 ring-primary' : ''} ${selectedId === node.id ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'} ${drag.isDragging ? 'relative z-20' : ''}`}
        data-testid={`tree-node-${node.id}`}
      >
        {node.has_children ? <button type="button" onClick={() => onToggle(node.id)} aria-label={`${open ? '收起' : '展开'}${node.title}`} className="flex h-7 w-5 shrink-0 items-center justify-center" aria-expanded={open}>{open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</button> : <span className="w-5 shrink-0" />}
        <button type="button" onClick={() => onNavigate(documentUrl(node.id, routeProjectId))} className="min-w-0 flex-1 truncate py-1.5 text-left text-sm" title={node.title}>{node.title}</button>
        {canDrag && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{!atRoot && onMoveToRoot && <DropdownMenuItem onClick={() => onMoveToRoot(node)}><ArrowUpToLine />移到根级</DropdownMenuItem>}<DropdownMenuItem onClick={() => onRename(node)}><Pencil />重命名</DropdownMenuItem><DropdownMenuItem variant="destructive" onClick={() => onDelete(node)}><Trash2 />删除</DropdownMenuItem></DropdownMenuContent></DropdownMenu>}
      </div>
      {children}
    </div>
}

function RootDropZone({ dragActive }: { dragActive: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: 'drop:root', data: { kind: 'root', id: null } })
  const highlight = isOver || (dragActive && true)
  return (
    <div
      ref={setNodeRef}
      data-testid="tree-root-dropzone"
      aria-label="移到根级投放区"
      className={`mb-1 rounded-md border border-dashed px-2 py-2 text-center text-xs ${highlight ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'} ${dragActive ? 'min-h-10 border-solid' : ''}`}
    >
      拖到此处移到根级
    </div>
  )
}

function RenameDialog({ node, open, onOpenChange, onSaved }: { node: DocumentNode | null; open: boolean; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const { routeProjectId } = useCurrentProject()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (open && node) { setName(node.title); setError(null) } }, [open, node])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!node) return
    setSubmitting(true)
    try {
      await api.patch(withProject(`/documents/wiki/${node.id}`, routeProjectId), { title: name.trim() })
      onOpenChange(false)
      onSaved()
    } catch (err) { setError(err instanceof ApiError ? err.message : '重命名失败，请重试') } finally { setSubmitting(false) }
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>重命名</DialogTitle><DialogDescription>只会修改当前 Wiki 的标题。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div className="space-y-1.5"><Label htmlFor="node-name">名称</Label><Input id="node-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} required maxLength={256} /></div>{error && <p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="submit" disabled={submitting}>{submitting ? '保存中…' : '保存'}</Button></DialogFooter></form></DialogContent></Dialog>
}

// REQ-59:断链点击创建——以断链原文预填标题建页,随后重存源页让 doc_link 接上
function CreateFromBrokenLinkDialog({ initialTitle, source, open, onOpenChange, onCreated }: { initialTitle: string; source: DocumentRow | null; open: boolean; onOpenChange: (open: boolean) => void; onCreated: (createdId: string) => void }) {
  const [title, setTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const { projectId, routeProjectId } = useCurrentProject()
  useEffect(() => { if (open) { setTitle(initialTitle); setError(null) } }, [open, initialTitle])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!projectId) return
    setSubmitting(true)
    try {
      const created = await api.post<DocumentRow>(`/projects/${projectId}/documents/wiki`, { title: title.trim(), doc_type: 'wiki', content: `---\ndoc_kind: concept\n---\n\n(从断链创建,待补充)` })
      if (source) {
        // 目标页就绪后重存源页(同内容)触发双链重解析,断链接上
        await api.patch<DocumentRow>(withProject(`/documents/wiki/${source.id}`, routeProjectId), { content: source.content ?? '' })
      }
      onOpenChange(false)
      onCreated(created.id)
    } catch (err) { setError(err instanceof ApiError ? err.message : '创建失败，请重试') } finally { setSubmitting(false) }
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>创建断链页面</DialogTitle><DialogDescription>以断链原文为标题新建 Wiki 页,并让源页面的链接接上。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div className="space-y-1.5"><Label htmlFor="broken-link-title">标题</Label><Input id="broken-link-title" autoComplete="off" value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={256} /></div>{error && <p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="submit" disabled={submitting}>{submitting ? '创建中…' : '创建页面'}</Button></DialogFooter></form></DialogContent></Dialog>
}

function ModuleTreeSidebar({ selected, onNavigate, readOnly }: { selected: { id: string; kind: 'document' } | null; onNavigate: (url: string) => void; readOnly: boolean }) {
  const { projectId, currentProject, routeProjectId } = useCurrentProject()
  const role = useProjectRole()
  const canEdit = !readOnly && (role === 'owner' || role === 'editor')
  const qc = useQueryClient()
  const [titleFilter, setTitleFilter] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [dragActive, setDragActive] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [actionNode, setActionNode] = useState<DocumentNode | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteImpact, setDeleteImpact] = useState<{ documents: number } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  useEffect(() => {
    if (!projectId || !selected?.id) return
    void api.get<{ items: DocumentNode[] }>(`/projects/${projectId}/documents/wiki/ancestors/document/${selected.id}`).then((result) => setExpanded((current) => new Set([...current, ...result.items.slice(0, -1).map((node) => node.id)]))).catch(() => undefined)
  }, [projectId, selected?.id])
  if (!projectId || !currentProject) return null
  async function invalidate() { await Promise.all([qc.invalidateQueries({ queryKey: ['document-tree', projectId] }), qc.invalidateQueries({ queryKey: ['document-node'] })]) }
  function createDocument(parentId: string | null | undefined) {
    const container = parentId === undefined ? (selected?.kind === 'document' ? selected.id : null) : parentId
    onNavigate(`${moduleBase(routeProjectId)}?mode=new${container ? `&container_id=${container}` : ''}`)
  }
  function moveToRoot(node: DocumentNode) {
    const plan = planDocumentMove('wiki', 'document', node.id, 'root', null)
    if (!plan) return
    void (async () => {
      try { await api.post(withProject(plan.path, routeProjectId), plan.body); await invalidate() } catch (err) { setActionError(err instanceof ApiError ? err.message : '移动失败') }
    })()
  }
  async function handleMoveEnd(event: DragEndEvent) {
    const dragData = event.active.data.current as { kind: 'document'; id: string } | undefined
    const overData = event.over?.data.current as { kind: 'document' | 'root'; id: string | null } | undefined
    if (!dragData || !overData) return
    const plan = planDocumentMove('wiki', dragData.kind, dragData.id, overData.kind, overData.id)
    if (!plan) return
    try { await api.post(withProject(plan.path, routeProjectId), plan.body); await invalidate() } catch (err) { setActionError(err instanceof ApiError ? err.message : '移动失败') }
  }
  function beginDelete(node: DocumentNode) {
    try { void api.get<{ documents: number }>(withProject(`/documents/wiki/${node.id}/delete-impact`, routeProjectId)).then((impact) => { setDeleteImpact(impact); setActionNode(node); setDeleteOpen(true) }).catch(() => setActionError('无法获取删除影响范围')) } catch (err) { setActionError(err instanceof ApiError ? err.message : '无法获取删除影响范围') }
  }
  async function confirmDelete() {
    if (!actionNode) return
    try { await api.post(withProject(`/documents/wiki/${actionNode.id}/delete`, routeProjectId)); setDeleteOpen(false); await invalidate(); onNavigate(moduleBase(routeProjectId)) } catch (err) { setActionError(err instanceof ApiError ? err.message : '删除失败') }
  }
  return <aside className="flex h-full min-h-0 w-64 shrink-0 flex-col border-r bg-background" aria-label="Wiki 文件组织"><div className="border-b px-4 py-4"><p className="font-semibold">Wiki</p><p className="mt-1 truncate text-xs text-muted-foreground">{currentProject.name}</p></div><div className="border-b p-3"><Input aria-label="搜索文档" autoComplete="off" placeholder="搜索文档" value={titleFilter} onChange={(event) => setTitleFilter(event.target.value)} /></div>{canEdit && <div className="flex justify-end border-b p-3"><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-sm" aria-label="新建"><Plus className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onClick={() => createDocument(null)}>新建 Wiki</DropdownMenuItem>{selected?.kind === 'document' && <DropdownMenuItem onClick={() => createDocument(selected.id)}>新建子 Wiki</DropdownMenuItem>}</DropdownMenuContent></DropdownMenu></div>}<div className="min-h-0 flex-1 overflow-y-auto p-3"><DndContext sensors={sensors} collisionDetection={rootZoneFirstPointerWithin} onDragStart={() => setDragActive(true)} onDragCancel={() => setDragActive(false)} onDragEnd={(event) => { setDragActive(false); void handleMoveEnd(event) }}><div className="sticky top-0 z-10 -mx-3 mb-1 bg-background px-3 pt-1">{canEdit && <RootDropZone dragActive={dragActive} />}</div><TreeChildren projectId={projectId} parentId={null} filter={titleFilter} expanded={expanded} onToggle={(id) => setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next })} onNavigate={onNavigate} selectedId={selected?.id} canEdit={canEdit} onMoveToRoot={moveToRoot} onRename={(node) => { setActionNode(node); setRenameOpen(true) }} onDelete={(node) => void beginDelete(node)} /></DndContext></div><ErrorNotification message={actionError} /><RenameDialog node={actionNode} open={renameOpen} onOpenChange={setRenameOpen} onSaved={invalidate} /><Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>确认删除</DialogTitle><DialogDescription>将软删除 {deleteImpact?.documents ?? 0} 篇文档。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void confirmDelete()}>删除</Button></DialogFooter></DialogContent></Dialog></aside>
}

// REQ-59 ⑤:INDEX 视图(index-first 阅读;后端投影,零维护)
function WikiIndexView({ onNavigate, onCreate }: { onNavigate: (url: string) => void; onCreate?: () => void }) {
  const { projectId, currentProject, routeProjectId } = useCurrentProject()
  const { data: index, isLoading, error } = useQuery({ queryKey: ['wiki-index', projectId], queryFn: () => api.get<WikiIndex>(`/projects/${projectId}/documents/index`) })
  if (!projectId || !currentProject) return null
  if (isLoading) return <main className="flex flex-1 items-center justify-center p-10"><p className="text-sm text-muted-foreground">加载中…</p></main>
  if (error) return <main className="flex flex-1 items-center justify-center p-10"><ErrorNotification message={(error as Error).message} /></main>
  const sections = index?.sections ?? []
  const lint = index?.lint
  return <main className="min-w-0 flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-4xl px-6 py-10 sm:px-10">
    <div className="flex flex-wrap items-start justify-between gap-4 border-b pb-5">
      <div>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Index · 自动生成</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">{currentProject.name} 知识 INDEX</h1>
        <p className="mt-2 text-sm text-muted-foreground">{index?.total ?? 0} 页 · 按形态分节 · 永不失真(从页面 frontmatter 投影,无需维护)</p>
      </div>
      {onCreate && <Button onClick={onCreate}><Plus className="mr-2 h-4 w-4" />新建 Wiki</Button>}
    </div>
    {lint && (lint.missing_kind.length > 0 || lint.broken_links.length > 0) && <section className="mt-6 rounded-xl border border-dashed p-5" aria-label="维护信号" data-testid="index-lint">
      <h2 className="text-sm font-medium text-muted-foreground">维护信号(lint)</h2>
      <ul className="mt-2 space-y-1 text-sm">
        {lint.missing_kind.length > 0 && <li>· {lint.missing_kind.length} 页未标注形态(doc_kind),暂列「未分类」</li>}
        {lint.missing_summary.length > 0 && <li>· {lint.missing_summary.length} 页缺 summary,目录行回退正文截断</li>}
        {lint.broken_links.length > 0 && <li>· {lint.broken_links.length} 处断链{lint.broken_links[0] ? `(如 ${lint.broken_links[0].from_title ?? lint.broken_links[0].from} → 「${lint.broken_links[0].raw_text}」)` : ''}</li>}
      </ul>
    </section>}
    <div className="mt-8 space-y-10">
      {sections.map((section) => <section key={section.kind ?? 'uncategorized'} aria-label={`${section.label}分节`}>
        <div className="flex items-center gap-2"><ListTree className="h-4 w-4 text-muted-foreground" /><h2 className="text-lg font-semibold">{section.label}</h2><span className="text-xs text-muted-foreground">{section.items.length} 页</span></div>
        <ul className="mt-3 divide-y rounded-xl border" data-testid={`index-section-${section.kind ?? 'uncategorized'}`}>
          {section.items.map((row) => <li key={row.id} className="px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <a href={documentUrl(row.id, routeProjectId)} onClick={(event) => { event.preventDefault(); onNavigate(documentUrl(row.id, routeProjectId)) }} className="font-medium hover:underline"><span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{row.id}</span>{row.title}</a>
              <span className="text-xs text-muted-foreground">{new Date(row.updated_at).toLocaleString()} · {authorDisplayName(row.author)}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{row.summary}{row.missing_summary && <span className="ml-1 text-xs text-muted-foreground/70">(正文截断)</span>}</p>
          </li>)}
        </ul>
      </section>)}
      {sections.length === 0 && <p className="text-sm text-muted-foreground">项目还没有 Wiki 页面。从一条决策或一次复盘开始记录。</p>}
    </div>
  </div></main>
}

function DocumentEditor({ document, containerId, onDirtyChange, onRegisterSave, onSaved, onCancel }: { document?: DocumentRow; containerId: string | null; onDirtyChange: (dirty: boolean) => void; onRegisterSave: (save: () => Promise<boolean>) => void; onSaved: (document: DocumentRow) => void; onCancel: () => void }) {
  const { projectId, routeProjectId } = useCurrentProject()
  const qc = useQueryClient()
  const [title, setTitle] = useState(document?.title ?? '')
  const [content, setContent] = useState(document?.content ?? '')
  const lookup = useProjectCompletion(projectId)
  const [uploading, setUploading] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [linkWarnings, setLinkWarnings] = useState<{ count: number; items: { raw_text: string; reason: string }[] } | null>(null)
  function markDirty() { if (!dirty) { setDirty(true); onDirtyChange(true) } }
  async function save(): Promise<boolean> {
    if (!projectId || uploading) return false
    setSubmitting(true)
    try {
      const payload = { title: title.trim() || '无标题', content }
      const saved = document ? await api.patch<DocumentRow>(withProject(`/documents/wiki/${document.id}`, routeProjectId), payload) : await api.post<DocumentRow>(`/projects/${projectId}/documents/wiki`, { ...payload, doc_type: 'wiki' as const, parent_id: containerId })
      await Promise.all([qc.invalidateQueries({ queryKey: ['document-tree', projectId] }), qc.invalidateQueries({ queryKey: ['document-node', 'wiki', saved.id] })])
      if (dirty) { setDirty(false); onDirtyChange(false) }
      if (saved.reference_warning && saved.reference_warning.count > 0) {
        setLinkWarnings(saved.reference_warning)
        return true // 保存成功但先展示断链提示,由用户继续导航
      }
      onSaved(saved)
      return true
    } catch (err) { setError(err instanceof ApiError ? err.message : '保存失败，请重试'); return false } finally { setSubmitting(false) }
  }
  useEffect(() => { onRegisterSave(save) })
  return <form onSubmit={(event) => { event.preventDefault(); void save() }} className="flex min-w-0 flex-1 flex-col"><ErrorNotification message={error} /><header className="border-b bg-background"><div className="mx-auto flex min-h-14 w-full max-w-5xl items-center justify-between gap-3 px-5 sm:px-8"><div className="flex items-center gap-3"><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">Wiki</span><span className="hidden text-xs text-muted-foreground sm:block">{dirty ? '未保存的更改' : document ? '已保存' : '尚未创建'}</span></div><div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={linkWarnings && document ? () => { const saved = document; setLinkWarnings(null); onSaved(saved) } : onCancel}>{linkWarnings ? '继续' : '取消'}</Button><Button type="submit" size="sm" disabled={submitting || uploading}>{submitting ? '保存中…' : '保存'}</Button></div></div></header>{linkWarnings && <div className="border-b border-dashed bg-muted/40 px-5 py-3 sm:px-8" role="status" data-testid="link-warnings"><div className="mx-auto max-w-5xl text-sm"><p className="font-medium">已保存,但检测到 {linkWarnings.count} 处断链(保留原文,不阻塞):</p><ul className="mt-1 list-disc pl-5 text-muted-foreground">{linkWarnings.items.map((item) => <li key={item.raw_text}>[[{item.raw_text}]] — {item.reason}</li>)}</ul></div></div>}<main className="flex flex-1 flex-col bg-muted/30"><article data-testid="document-writing-canvas" className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-8 sm:px-10 sm:py-10"><h1 className="sr-only">{document ? `编辑${document.title}` : '新建 Wiki'}</h1><div className="text-xs text-muted-foreground">{document ? `Wiki / ${document.title || '未命名文档'}` : 'Wiki / 新建文档'}(正文顶部可写 YAML frontmatter:summary/doc_kind/tags/aliases;[[双链]]保存时自动落表)</div><div className="mt-5"><Label htmlFor="document-title" className="sr-only">标题</Label><Input id="document-title" autoComplete="off" value={title} onChange={(event) => { setTitle(event.target.value); markDirty() }} maxLength={256} placeholder="无标题" className="h-auto rounded-none border-0 bg-transparent px-0 py-0 text-[2.5rem] font-semibold leading-tight tracking-[-0.045em] shadow-none placeholder:text-muted-foreground/55 focus-visible:ring-0 md:!text-5xl" /></div><section className="mt-10 flex-1 pb-24"><MarkdownComposer className="[--writing-height:26rem]" value={content} onChange={(markdown) => { setContent(markdown); markDirty() }} disabled={submitting} lookup={lookup} upload={projectId ? projectFileUpload(projectId) : undefined} onUploadPending={setUploading} /></section></article></main></form>
}

function LinkBadge({ broken }: { broken: boolean }) {
  return broken ? <span className="rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] text-destructive">断链</span> : null
}

function DocumentDetail({ document, onEdit, onNavigate, readOnly }: { document: DocumentRow; onEdit: () => void; onNavigate: (url: string) => void; readOnly: boolean }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const role = useProjectRole()
  const { projectId, routeProjectId } = useCurrentProject()
  const canEdit = !readOnly && (role === 'owner' || role === 'editor')
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [brokenCreate, setBrokenCreate] = useState<string | null>(null)
  const { data: versions } = useQuery({ queryKey: ['document-versions', 'wiki', document.id, routeProjectId], queryFn: () => api.get<{ items: DocumentVersionRow[] }>(withProject(`/documents/wiki/${document.id}/versions`, routeProjectId)), enabled: versionsOpen })

  const links: WikiLinks | undefined = document.links
  const metadata = document.metadata ?? {}
  const kind = typeof metadata.doc_kind === 'string' ? metadata.doc_kind : null
  const summary = typeof metadata.summary === 'string' ? metadata.summary : null
  const tags = Array.isArray(metadata.tags) ? metadata.tags.map(String) : []
  const aliases = Array.isArray(metadata.aliases) ? metadata.aliases.map(String) : []
  async function rollback(versionNo: number) { try { await api.post(withProject(`/documents/wiki/${document.id}/rollback`, routeProjectId), { version_no: versionNo }); setRollbackTarget(null); setVersionsOpen(false); await qc.invalidateQueries({ queryKey: ['document-node'] }) } catch (err) { setError(err instanceof ApiError ? err.message : '回滚失败') } }
  async function remove() { try { await api.post(withProject(`/documents/wiki/${document.id}/delete`, routeProjectId)); navigate(moduleBase(routeProjectId)) } catch (err) { setError(err instanceof ApiError ? err.message : '删除失败') } }
  function handleContentClick(event: MouseEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement
    const broken = target.closest('a.wiki-link-broken') as HTMLAnchorElement | null
    if (broken) { event.preventDefault(); if (canEdit) setBrokenCreate(broken.dataset.wikiCreate ?? ''); return }
    const live = target.closest('a.wiki-link') as HTMLAnchorElement | null
    if (live?.dataset.wikiCode) { event.preventDefault(); onNavigate(documentUrl(live.dataset.wikiCode, routeProjectId)) }
  }
  return <main className="mx-auto w-full max-w-5xl px-6 py-10 sm:px-10"><div className="mx-auto max-w-3xl"><div className="flex flex-wrap items-start justify-between gap-4 border-b pb-5"><div><div className="flex flex-wrap items-center gap-2"><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{kindLabel(kind)}</span><span className="font-mono text-xs text-muted-foreground">{document.id}</span></div><h1 className="mt-3 text-3xl font-semibold tracking-tight">{document.title}</h1><p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">更新于 {new Date(document.updated_at).toLocaleString()} · <AuthorBadge author={document.author} compact /></p></div>{canEdit && <div className="flex gap-2"><Button variant="destructive" onClick={() => setDeleteOpen(true)}><Trash2 className="mr-2 h-4 w-4" />删除</Button><Button variant="outline" onClick={() => setVersionsOpen(true)}><History className="mr-2 h-4 w-4" />版本</Button><Button onClick={onEdit}><Pencil className="mr-2 h-4 w-4" />编辑</Button></div>}</div>
  {summary && <p className="mt-4 rounded-lg bg-muted/50 px-4 py-3 text-sm text-muted-foreground" data-testid="frontmatter-summary">{summary}</p>}
  {(tags.length > 0 || aliases.length > 0) && <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs" data-testid="frontmatter-tags">
    {tags.map((tag) => <span key={`tag-${tag}`} className="rounded-full border px-2 py-0.5 text-muted-foreground">#{tag}</span>)}
    {aliases.map((alias) => <span key={`alias-${alias}`} className="rounded-full border border-dashed px-2 py-0.5 text-muted-foreground" title="别名(参与双链与检索消歧)">别名:{alias}</span>)}
  </div>}
  <section className="mt-8" onClick={handleContentClick}><VditorMarkdownViewer markdown={document.content ?? ''} wikiLinks={links} /></section>
  {links && (links.outgoing.length > 0 || links.incoming.length > 0) && <section className="mt-8 grid gap-4 sm:grid-cols-2" aria-label="双链与反链">
    <div className="rounded-xl border p-5"><h2 className="flex items-center gap-2 font-medium"><Link2 className="h-4 w-4" />链接({links.outgoing.length})</h2><ul className="mt-3 space-y-2 text-sm">{links.outgoing.length ? links.outgoing.map((link, index) => <li key={`${link.raw_text}-${index}`} className="flex flex-wrap items-center gap-2">{link.broken || !link.to_code
      ? <button type="button" className="text-destructive hover:underline" title="断链:点击创建该页面" disabled={!canEdit} onClick={() => setBrokenCreate(link.raw_text)}>{link.display ?? link.raw_text}{link.section ? ` #${link.section}` : ''}</button>
      : <a href={documentUrl(link.to_code, routeProjectId)} className="text-primary hover:underline" onClick={(event) => { event.preventDefault(); onNavigate(documentUrl(link.to_code!, routeProjectId)) }}>{link.display ?? link.to_title ?? link.raw_text}{link.section ? ` #${link.section}` : ''}</a>}
      <LinkBadge broken={link.broken || !link.to_code} /></li>) : <li className="text-muted-foreground">暂无出链</li>}</ul></div>
    <div className="rounded-xl border p-5"><h2 className="flex items-center gap-2 font-medium"><Link2 className="h-4 w-4" />反链({links.incoming.length})</h2><ul className="mt-3 space-y-2 text-sm">{links.incoming.length ? links.incoming.map((link, index) => <li key={`${link.from_code}-${index}`}><a href={documentUrl(link.from_code, routeProjectId)} className="text-primary hover:underline" onClick={(event) => { event.preventDefault(); onNavigate(documentUrl(link.from_code, routeProjectId)) }}>{link.from_title}</a><span className="text-muted-foreground"> → 此处(经「{link.raw_text}」)</span></li>) : <li className="text-muted-foreground">暂无反链</li>}</ul></div>
  </section>}
  <section className="mt-8"><AttachmentList targetType="document" targetId={document.id} projectId={routeProjectId} readOnly={readOnly} /></section></div><ErrorNotification message={error} />
  <CreateFromBrokenLinkDialog initialTitle={brokenCreate ?? ''} source={document} open={brokenCreate !== null} onOpenChange={(open) => { if (!open) setBrokenCreate(null) }} onCreated={async (createdId) => { await qc.invalidateQueries({ queryKey: ['document-node'] }); await qc.invalidateQueries({ queryKey: ['wiki-index', projectId] }); navigate(`${documentUrl(createdId, routeProjectId)}?mode=edit`) }} />
  <Dialog open={versionsOpen} onOpenChange={setVersionsOpen}><DialogContent><DialogHeader><DialogTitle>版本历史</DialogTitle><DialogDescription>回滚会恢复该版本内容并创建新版本。</DialogDescription></DialogHeader><div className="max-h-96 space-y-2 overflow-y-auto">{versions?.items.map((version) => <div key={version.id} className="flex items-center justify-between rounded border p-3 text-sm"><span>版本 {version.version_no} · {version.title}{version.author ? ` · ${authorDisplayName(version.author)}` : ''}</span>{canEdit && <Button size="sm" variant="outline" onClick={() => setRollbackTarget(version.version_no)}><RotateCcw className="mr-1.5 h-3.5 w-3.5" />回滚</Button>}</div>)}</div></DialogContent></Dialog><Dialog open={rollbackTarget !== null} onOpenChange={(open) => !open && setRollbackTarget(null)}><DialogContent><DialogHeader><DialogTitle>确认回滚</DialogTitle><DialogDescription>标题和正文会恢复为所选版本。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setRollbackTarget(null)}>取消</Button><Button onClick={() => rollbackTarget !== null && void rollback(rollbackTarget)}>确认回滚</Button></DialogFooter></DialogContent></Dialog><Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>删除文档</DialogTitle><DialogDescription>此操作会将文档移入已删除状态。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void remove()}>确认删除</Button></DialogFooter></DialogContent></Dialog></main>
}

export function DocumentWorkbenchPage({ module, readOnly = false }: { module: DocumentType; readOnly?: boolean }) {
  return module === 'wiki' ? <WikiWorkbenchPage readOnly={readOnly} /> : null
}

function WikiWorkbenchPage({ readOnly }: { readOnly: boolean }) {
  const params = useParams<{ id?: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { currentProject, isLoading: loadingProject, routeProjectId } = useCurrentProject()
  const { registerBlocker } = useDocumentNavigation()
  const role = useProjectRole()
  const selected = parseNodeFromRoute(params.id)
  const mode = new URLSearchParams(location.search).get('mode')
  const containerId = new URLSearchParams(location.search).get('container_id')
  const [dirty, setDirty] = useState(false)
  const [pendingUrl, setPendingUrl] = useState<string | null>(null)
  const saveRef = useRef<() => Promise<boolean>>(async () => false)
  const { data: document, isLoading: documentLoading, error: documentError } = useQuery({
    queryKey: ['document-node', 'wiki', selected?.id, routeProjectId ?? currentProject?.id],
    queryFn: async () => {
      const path = `/documents/wiki/${encodeURIComponent(selected!.id)}`
      const result = await api.get<DocumentRow>(withProject(path, routeProjectId))
      if (routeProjectId && result.project_id !== routeProjectId) throw new ApiError(404, '文档不存在或无访问权限')
      return result
    },
    enabled: selected?.kind === 'document',
  })
  const canEdit = !readOnly && (role === 'owner' || role === 'editor')
  function requestNavigation(url: string) { if (dirty) setPendingUrl(url); else navigate(url) }
  async function saveAndNavigate() { if (pendingUrl && await saveRef.current()) { const target = pendingUrl; setPendingUrl(null); navigate(target) } }
  useEffect(() => { registerBlocker((target) => { if (!dirty) return false; setPendingUrl(target); return true }); return () => registerBlocker(null) }, [dirty, registerBlocker])
  if (loadingProject) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <NoProject />
  if (documentError) return <ErrorNotification message={(documentError as Error).message} />
  const editing = mode === 'new' || mode === 'edit'
  return <div className="-m-6 flex h-[calc(100dvh-3rem)] min-h-0 bg-background"><ModuleTreeSidebar selected={selected} onNavigate={requestNavigation} readOnly={readOnly} />{documentLoading ? <p className="p-8 text-sm text-muted-foreground">加载中…</p> : mode === 'new' && canEdit ? <DocumentEditor key={`new-wiki-${containerId ?? 'root'}`} containerId={containerId} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(saved.id, routeProjectId))} onCancel={() => requestNavigation(moduleBase(routeProjectId))} /> : document && editing && canEdit ? <DocumentEditor key={document.id} document={document} containerId={document.parent_id} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(saved.id, routeProjectId))} onCancel={() => requestNavigation(documentUrl(document.id, routeProjectId))} /> : document ? <DocumentDetail document={document} readOnly={readOnly} onEdit={() => navigate(`${documentUrl(document.id, routeProjectId)}?mode=edit`)} onNavigate={requestNavigation} /> : <WikiIndexView onNavigate={requestNavigation} onCreate={!readOnly ? () => requestNavigation(`${moduleBase(routeProjectId)}?mode=new`) : undefined} />}<Dialog open={pendingUrl !== null} onOpenChange={(open) => !open && setPendingUrl(null)}><DialogContent><DialogHeader><DialogTitle>未保存的更改</DialogTitle><DialogDescription>切换前请选择如何处理当前文档。</DialogDescription></DialogHeader><DialogFooter className="sm:justify-between"><Button variant="ghost" onClick={() => setPendingUrl(null)}>留在当前文档</Button><div className="flex gap-2"><Button variant="outline" onClick={() => { const target = pendingUrl; setDirty(false); setPendingUrl(null); if (target) navigate(target) }}>放弃更改并切换</Button><Button onClick={() => void saveAndNavigate()}>保存并切换</Button></div></DialogFooter></DialogContent></Dialog></div>
}
