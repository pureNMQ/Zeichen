import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, History, MoreHorizontal, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { VditorIrEditor, VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ErrorNotification } from '@/components/ui/notification'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, ApiError, type DocumentDirectoryRow, type DocumentNode, type DocumentRow, type DocumentType, type DocumentVersionRow, type ReferenceRow } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { useDocumentNavigation } from '@/lib/document-navigation'

export const DOCUMENT_TYPES: { type: DocumentType; label: string }[] = [
  { type: 'wiki', label: 'Wiki' },
  { type: 'glossary', label: '词条' },
]

function documentLabel(type: DocumentType) {
  return DOCUMENT_TYPES.find((item) => item.type === type)?.label ?? '文档'
}

function moduleBase(type: DocumentType) {
  return `/documents/${type}`
}

function documentUrl(type: DocumentType, id: string) {
  return type === 'wiki' ? `/documents/wiki/${id}` : `/documents/glossary/term/${id}`
}

function directoryUrl(id: string) {
  return `/documents/glossary/directory/${id}`
}

function nodeUrl(type: DocumentType, node: DocumentNode) {
  return node.node_kind === 'directory' ? directoryUrl(node.id) : documentUrl(type, node.id)
}

function parseNodeFromRoute(type: DocumentType, id: string | undefined, routeNodeKind?: 'document' | 'directory') {
  if (!id) return null
  return { id, kind: type === 'wiki' || routeNodeKind !== 'directory' ? 'document' as const : 'directory' as const }
}

function NoProject() {
  return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">请先在侧边栏选择当前项目。</CardContent></Card>
}

function treeKey(projectId: string, module: DocumentType, parentId: string | null) {
  return ['document-tree', projectId, module, parentId]
}

function TreeChildren({ projectId, module, parentId, expanded, onToggle, onNavigate, selectedId, canEdit, onRename, onDelete }: {
  projectId: string
  module: DocumentType
  parentId: string | null
  expanded: Set<string>
  onToggle: (id: string) => void
  onNavigate: (url: string) => void
  selectedId?: string
  canEdit: boolean
  onRename: (node: DocumentNode) => void
  onDelete: (node: DocumentNode) => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: treeKey(projectId, module, parentId),
    queryFn: () => api.get<{ items: DocumentNode[]; next_cursor: string | null }>(`/projects/${projectId}/documents/${module}/children?${parentId ? `parent_id=${parentId}&` : ''}limit=100`),
  })
  if (isLoading) return <p className="px-3 py-2 text-sm text-muted-foreground">加载中…</p>
  if (!data?.items.length) return parentId ? null : <p className="px-3 py-2 text-sm text-muted-foreground">暂无内容</p>
  return <div className={parentId ? 'ml-3 border-l pl-1.5' : 'space-y-0.5'}>{data.items.map((node) => {
    const open = expanded.has(node.id)
    return <div key={node.id}>
      <div className={`group flex min-w-0 items-center gap-1 rounded-md pr-1 ${selectedId === node.id ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
        {node.has_children ? <button type="button" onClick={() => onToggle(node.id)} aria-label={`${open ? '收起' : '展开'}${node.title}`} className="flex h-7 w-5 shrink-0 items-center justify-center" aria-expanded={open}>{open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</button> : <span className="w-5 shrink-0" />}
        <button type="button" onClick={() => onNavigate(nodeUrl(module, node))} className="min-w-0 flex-1 truncate py-1.5 text-left text-sm" title={node.title}>{node.title}</button>
        {canEdit && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onClick={() => onRename(node)}><Pencil />重命名</DropdownMenuItem><DropdownMenuItem variant="destructive" onClick={() => onDelete(node)}><Trash2 />删除</DropdownMenuItem></DropdownMenuContent></DropdownMenu>}
      </div>
      {node.has_children && open && <TreeChildren projectId={projectId} module={module} parentId={node.id} expanded={expanded} onToggle={onToggle} onNavigate={onNavigate} selectedId={selectedId} canEdit={canEdit} onRename={onRename} onDelete={onDelete} />}
    </div>
  })}</div>
}

function RenameDialog({ node, module, open, onOpenChange, onSaved }: { node: DocumentNode | null; module: DocumentType; open: boolean; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (open && node) { setName(node.title); setError(null) } }, [open, node])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!node) return
    setSubmitting(true)
    try {
      const path = node.node_kind === 'directory' ? `/directories/${module}/${node.id}` : `/documents/${module}/${node.id}`
      await api.patch(path, node.node_kind === 'directory' ? { name: name.trim() } : { title: name.trim() })
      onOpenChange(false)
      onSaved()
    } catch (err) { setError(err instanceof ApiError ? err.message : '重命名失败，请重试') } finally { setSubmitting(false) }
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>重命名</DialogTitle><DialogDescription>只会修改当前节点的名称。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div className="space-y-1.5"><Label htmlFor="node-name">名称</Label><Input id="node-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} required maxLength={256} /></div>{error && <p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="submit" disabled={submitting}>{submitting ? '保存中…' : '保存'}</Button></DialogFooter></form></DialogContent></Dialog>
}

function CreateDirectoryDialog({ projectId, parentId, open, onOpenChange, onCreated }: { projectId: string; parentId: string | null; open: boolean; onOpenChange: (open: boolean) => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (open) { setName(''); setError(null) } }, [open])
  async function submit(event: FormEvent) {
    event.preventDefault(); setSubmitting(true)
    try { await api.post(`/projects/${projectId}/documents/glossary/directories`, { name: name.trim(), parent_id: parentId }); onOpenChange(false); onCreated() } catch (err) { setError(err instanceof ApiError ? err.message : '创建目录失败，请重试') } finally { setSubmitting(false) }
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>新建目录</DialogTitle><DialogDescription>目录用于组织词条。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div className="space-y-1.5"><Label htmlFor="directory-name">目录名称</Label><Input id="directory-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} required maxLength={256} /></div>{error && <p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="submit" disabled={submitting}>{submitting ? '创建中…' : '创建目录'}</Button></DialogFooter></form></DialogContent></Dialog>
}

function ModuleTreeSidebar({ module, selected, selectedNode, onNavigate }: { module: DocumentType; selected: { id: string; kind: 'document' | 'directory' } | null; selectedNode: DocumentNode | null; onNavigate: (url: string) => void }) {
  const { projectId, currentProject } = useCurrentProject()
  const role = useProjectRole()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const canEdit = role === 'owner' || role === 'editor'
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [renameOpen, setRenameOpen] = useState(false)
  const [directoryOpen, setDirectoryOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [actionNode, setActionNode] = useState<DocumentNode | null>(null)
  const [deleteImpact, setDeleteImpact] = useState<{ documents: number; directories: number } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  useEffect(() => {
    if (!projectId || !selected) return
    void api.get<{ items: DocumentNode[] }>(`/projects/${projectId}/documents/${module}/ancestors/${selected.kind}/${selected.id}`).then((result) => setExpanded((current) => new Set([...current, ...result.items.slice(0, -1).map((node) => node.id)]))).catch(() => undefined)
  }, [module, projectId, selected?.id, selected?.kind])
  async function invalidate() { await Promise.all([qc.invalidateQueries({ queryKey: ['document-tree', projectId, module] }), qc.invalidateQueries({ queryKey: ['document-node'] })]) }
  function createDocument(parentId?: string | null) {
    const container = parentId === undefined ? (module === 'wiki' ? (selected?.kind === 'document' ? selected.id : null) : (selected?.kind === 'directory' ? selected.id : selectedNode?.node_kind === 'document' ? selectedNode.directory_id : null)) : parentId
    onNavigate(`${moduleBase(module)}?mode=new${container ? `&container_id=${container}` : ''}`)
  }
  async function beginDelete(node: DocumentNode) {
    try { const path = node.node_kind === 'directory' ? `/directories/${module}/${node.id}/delete-impact` : `/documents/${module}/${node.id}/delete-impact`; setDeleteImpact(await api.get(path)); setActionNode(node); setDeleteOpen(true) } catch (err) { setActionError(err instanceof ApiError ? err.message : '无法获取删除影响范围') }
  }
  async function confirmDelete() {
    if (!actionNode) return
    try { const path = actionNode.node_kind === 'directory' ? `/directories/${module}/${actionNode.id}/delete` : `/documents/${module}/${actionNode.id}/delete`; await api.post(path); setDeleteOpen(false); await invalidate(); navigate(moduleBase(module)) } catch (err) { setActionError(err instanceof ApiError ? err.message : '删除失败') }
  }
  if (!projectId || !currentProject) return null
  return <aside className="flex w-64 shrink-0 flex-col border-r bg-background" aria-label={`${documentLabel(module)}文件组织`}><div className="border-b px-4 py-4"><p className="font-semibold">{documentLabel(module)}</p><p className="mt-1 truncate text-xs text-muted-foreground">{currentProject.name}</p></div><div className="border-b p-3"><Input aria-label="搜索文档（即将支持）" autoComplete="off" placeholder="搜索文档（即将支持）" disabled /></div>{canEdit && <div className="flex justify-end border-b p-3"><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-sm" aria-label="新建"><Plus className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{module === 'wiki' ? <><DropdownMenuItem onClick={() => createDocument(null)}>新建 Wiki</DropdownMenuItem>{selected?.kind === 'document' && <DropdownMenuItem onClick={() => createDocument(selected.id)}>新建子 Wiki</DropdownMenuItem>}</> : <><DropdownMenuItem onClick={() => createDocument()}>新建词条</DropdownMenuItem><DropdownMenuItem onClick={() => setDirectoryOpen(true)}>新建目录</DropdownMenuItem></>}</DropdownMenuContent></DropdownMenu></div>}<div className="flex-1 overflow-y-auto p-3"><TreeChildren projectId={projectId} module={module} parentId={null} expanded={expanded} onToggle={(id) => setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next })} onNavigate={onNavigate} selectedId={selected?.id} canEdit={canEdit} onRename={(node) => { setActionNode(node); setRenameOpen(true) }} onDelete={(node) => void beginDelete(node)} /></div><ErrorNotification message={actionError} /><RenameDialog node={actionNode} module={module} open={renameOpen} onOpenChange={setRenameOpen} onSaved={invalidate} />{module === 'glossary' && <CreateDirectoryDialog projectId={projectId} parentId={selected?.kind === 'directory' ? selected.id : null} open={directoryOpen} onOpenChange={setDirectoryOpen} onCreated={invalidate} />}<Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>确认删除</DialogTitle><DialogDescription>将软删除 {deleteImpact?.documents ?? 0} 篇文档和 {deleteImpact?.directories ?? 0} 个目录。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void confirmDelete()}>删除</Button></DialogFooter></DialogContent></Dialog></aside>
}

function DocumentEditor({ module, document, containerId, onDirtyChange, onRegisterSave, onSaved, onCancel }: { module: DocumentType; document?: DocumentRow; containerId: string | null; onDirtyChange: (dirty: boolean) => void; onRegisterSave: (save: () => Promise<boolean>) => void; onSaved: (document: DocumentRow) => void; onCancel: () => void }) {
  const { projectId } = useCurrentProject()
  const qc = useQueryClient()
  const [title, setTitle] = useState(document?.title ?? '')
  const [content, setContent] = useState(document?.content ?? '')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dirty, setDirty] = useState(false)
  function markDirty() { setDirty(true); onDirtyChange(true) }
  useEffect(() => () => onDirtyChange(false), [onDirtyChange])
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn) }, [dirty])
  async function save(stayOnPage = false): Promise<boolean> {
    setError(null); setSubmitting(true)
    try {
      const payload = { title: title.trim(), content }
      const saved = document ? await api.patch<DocumentRow>(`/documents/${module}/${document.id}`, payload) : await api.post<DocumentRow>(`/projects/${projectId}/documents/${module}`, { ...payload, doc_type: module, ...(module === 'wiki' ? { parent_id: containerId } : { directory_id: containerId }) })
      await Promise.all([qc.invalidateQueries({ queryKey: ['document-tree', projectId, module] }), qc.invalidateQueries({ queryKey: ['document-node', module, saved.id] })])
      setDirty(false); onDirtyChange(false); if (!stayOnPage) onSaved(saved); return true
    } catch (err) { setError(err instanceof ApiError ? err.message : '保存失败，请重试'); return false } finally { setSubmitting(false) }
  }
  useEffect(() => { onRegisterSave(() => save(true)) }, [title, content, document?.id, containerId])
  return <form onSubmit={(event) => { event.preventDefault(); void save() }} className="flex min-w-0 flex-1 flex-col"><ErrorNotification message={error} /><header className="border-b bg-background"><div className="mx-auto flex min-h-14 w-full max-w-5xl items-center justify-between gap-3 px-5 sm:px-8"><div className="flex items-center gap-3"><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{documentLabel(module)}</span><span className="hidden text-xs text-muted-foreground sm:block">{dirty ? '未保存的更改' : document ? '已保存' : '尚未创建'}</span></div><div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={onCancel}>取消</Button><Button type="submit" size="sm" disabled={submitting}>{submitting ? '保存中…' : '保存'}</Button></div></div></header><main className="flex flex-1 flex-col bg-muted/30"><article data-testid="document-writing-canvas" className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-8 sm:px-10 sm:py-10"><h1 className="sr-only">{document ? `编辑${document.title}` : `新建${documentLabel(module)}`}</h1><div className="text-xs text-muted-foreground">{document ? `${documentLabel(module)} / ${document.title || '未命名文档'}` : `${documentLabel(module)} / 新建文档`}</div><div className="mt-5"><Label htmlFor="document-title" className="sr-only">标题</Label><Input id="document-title" autoComplete="off" value={title} onChange={(event) => { setTitle(event.target.value); markDirty() }} maxLength={256} placeholder="无标题" className="h-auto rounded-none border-0 bg-transparent px-0 py-0 text-[2.5rem] font-semibold leading-tight tracking-[-0.045em] shadow-none placeholder:text-muted-foreground/55 focus-visible:ring-0 md:!text-5xl" /></div><section className="mt-10 flex-1 pb-24"><Label id="document-content-label" className="sr-only">正文</Label><VditorIrEditor className="document-vditor min-h-[26rem]" initialMarkdown={content} onChange={(markdown) => { setContent(markdown); markDirty() }} disabled={submitting} ariaLabelledBy="document-content-label" /></section></article></main></form>
}

function DocumentDetail({ module, document, onEdit }: { module: DocumentType; document: DocumentRow; onEdit: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const role = useProjectRole()
  const canEdit = role === 'owner' || role === 'editor'
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data: versions } = useQuery({ queryKey: ['document-versions', module, document.id], queryFn: () => api.get<{ items: DocumentVersionRow[] }>(`/documents/${module}/${document.id}/versions`), enabled: versionsOpen })
  const { data: references } = useQuery({ queryKey: ['document-references', module, document.id], queryFn: () => api.get<{ count: number; items: ReferenceRow[] }>(`/documents/${module}/${document.id}/references`) })
  async function rollback(versionNo: number) { try { await api.post(`/documents/${module}/${document.id}/rollback`, { version_no: versionNo }); setRollbackTarget(null); setVersionsOpen(false); await qc.invalidateQueries({ queryKey: ['document-node'] }) } catch (err) { setError(err instanceof ApiError ? err.message : '回滚失败') } }
  async function remove() { try { await api.post(`/documents/${module}/${document.id}/delete`); navigate(moduleBase(module)) } catch (err) { setError(err instanceof ApiError ? err.message : '删除失败') } }
  return <main className="mx-auto w-full max-w-5xl px-6 py-10 sm:px-10"><div className="mx-auto max-w-3xl"><div className="flex flex-wrap items-start justify-between gap-4 border-b pb-5"><div><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{documentLabel(module)}</span><h1 className="mt-4 text-3xl font-semibold tracking-tight">{document.title}</h1><p className="mt-2 text-sm text-muted-foreground">更新于 {new Date(document.updated_at).toLocaleString()}</p></div>{canEdit && <div className="flex gap-2"><Button variant="destructive" onClick={() => setDeleteOpen(true)}><Trash2 className="mr-2 h-4 w-4" />删除</Button><Button variant="outline" onClick={() => setVersionsOpen(true)}><History className="mr-2 h-4 w-4" />版本</Button><Button onClick={onEdit}><Pencil className="mr-2 h-4 w-4" />编辑</Button></div>}</div><section className="mt-8"><VditorMarkdownViewer markdown={document.content ?? ''} /></section><section className="mt-8 rounded-xl border p-5"><h2 className="font-medium">引用</h2><div className="mt-3 space-y-2 text-sm">{references?.items.length ? references.items.map((reference) => <p key={reference.id}>{reference.from_id === document.id ? '引用至' : '被引用于'} {reference.from_id === document.id ? reference.to_type : reference.from_type}:{(reference.from_id === document.id ? reference.to_id : reference.from_id).slice(0, 8)}</p>) : <p className="text-muted-foreground">暂无引用</p>}</div></section></div><ErrorNotification message={error} /><Dialog open={versionsOpen} onOpenChange={setVersionsOpen}><DialogContent><DialogHeader><DialogTitle>版本历史</DialogTitle><DialogDescription>回滚会恢复该版本内容并创建新版本。</DialogDescription></DialogHeader><div className="max-h-96 space-y-2 overflow-y-auto">{versions?.items.map((version) => <div key={version.id} className="flex items-center justify-between rounded border p-3 text-sm"><span>版本 {version.version_no} · {version.title}</span>{canEdit && <Button size="sm" variant="outline" onClick={() => setRollbackTarget(version.version_no)}><RotateCcw className="mr-1.5 h-3.5 w-3.5" />回滚</Button>}</div>)}</div></DialogContent></Dialog><Dialog open={rollbackTarget !== null} onOpenChange={(open) => !open && setRollbackTarget(null)}><DialogContent><DialogHeader><DialogTitle>确认回滚</DialogTitle><DialogDescription>标题和正文会恢复为所选版本。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setRollbackTarget(null)}>取消</Button><Button onClick={() => rollbackTarget !== null && void rollback(rollbackTarget)}>确认回滚</Button></DialogFooter></DialogContent></Dialog><Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>删除文档</DialogTitle><DialogDescription>此操作会将文档移入已删除状态。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void remove()}>确认删除</Button></DialogFooter></DialogContent></Dialog></main>
}

export function DocumentWorkbenchPage({ module, routeNodeKind }: { module: DocumentType; routeNodeKind?: 'document' | 'directory' }) {
  const params = useParams<{ id?: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { currentProject, isLoading: loadingProject } = useCurrentProject()
  const { registerBlocker } = useDocumentNavigation()
  const role = useProjectRole()
  const selected = parseNodeFromRoute(module, params.id, routeNodeKind)
  const mode = new URLSearchParams(location.search).get('mode')
  const containerId = new URLSearchParams(location.search).get('container_id')
  const [dirty, setDirty] = useState(false)
  const [pendingUrl, setPendingUrl] = useState<string | null>(null)
  const saveRef = useRef<() => Promise<boolean>>(async () => false)
  const { data: document, isLoading: documentLoading, error: documentError } = useQuery({ queryKey: ['document-node', module, selected?.id], queryFn: () => api.get<DocumentRow>(`/documents/${module}/${selected?.id}`), enabled: selected?.kind === 'document' })
  const { data: directory } = useQuery({ queryKey: ['directory-node', module, selected?.id], queryFn: () => api.get<DocumentDirectoryRow>(`/directories/${module}/${selected?.id}`), enabled: selected?.kind === 'directory' && module === 'glossary' })
  const canEdit = role === 'owner' || role === 'editor'
  function requestNavigation(url: string) { if (dirty) setPendingUrl(url); else navigate(url) }
  async function saveAndNavigate() { if (pendingUrl && await saveRef.current()) { const target = pendingUrl; setPendingUrl(null); navigate(target) } }
  useEffect(() => { registerBlocker((target) => { if (!dirty) return false; setPendingUrl(target); return true }); return () => registerBlocker(null) }, [dirty, registerBlocker])
  if (loadingProject) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <NoProject />
  if (documentError) return <ErrorNotification message={(documentError as Error).message} />
  const editing = mode === 'new' || mode === 'edit'
  return <div className="-m-6 flex min-h-[calc(100vh-0.5px)] bg-background"><ModuleTreeSidebar module={module} selected={selected} selectedNode={document ?? directory ?? null} onNavigate={requestNavigation} />{documentLoading ? <p className="p-8 text-sm text-muted-foreground">加载中…</p> : mode === 'new' && canEdit ? <DocumentEditor key={`new-${module}-${containerId ?? 'root'}`} module={module} containerId={containerId} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(module, saved.id))} onCancel={() => requestNavigation(moduleBase(module))} /> : document && editing && canEdit ? <DocumentEditor key={document.id} module={module} document={document} containerId={document.parent_id ?? document.directory_id} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(module, saved.id))} onCancel={() => requestNavigation(documentUrl(module, document.id))} /> : document ? <DocumentDetail module={module} document={document} onEdit={() => navigate(`${documentUrl(module, document.id)}?mode=edit`)} /> : directory ? <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">{directory.name}</h1><p className="mt-2 text-sm text-muted-foreground">在左侧目录中选择词条，或新建词条。</p></div></main> : <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">{documentLabel(module)}</h1><p className="mt-2 text-sm text-muted-foreground">从左侧浏览文件组织，或新建文档。</p></div></main>}<Dialog open={pendingUrl !== null} onOpenChange={(open) => !open && setPendingUrl(null)}><DialogContent><DialogHeader><DialogTitle>未保存的更改</DialogTitle><DialogDescription>切换前请选择如何处理当前文档。</DialogDescription></DialogHeader><DialogFooter className="sm:justify-between"><Button variant="ghost" onClick={() => setPendingUrl(null)}>留在当前文档</Button><div className="flex gap-2"><Button variant="outline" onClick={() => { const target = pendingUrl; setDirty(false); setPendingUrl(null); if (target) navigate(target) }}>放弃更改并切换</Button><Button onClick={() => void saveAndNavigate()}>保存并切换</Button></div></DialogFooter></DialogContent></Dialog></div>
}
