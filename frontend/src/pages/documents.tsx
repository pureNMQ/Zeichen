import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { VditorIrEditor, VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorNotification } from '@/components/ui/notification'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, ApiError, type ApiSchemaField, type DocumentDirectoryRow, type DocumentNode, type DocumentRow, type DocumentType, type DocumentVersionRow, type ReferenceRow } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { useDocumentNavigation } from '@/lib/document-navigation'

export const DOCUMENT_TYPES: { type: DocumentType; label: string }[] = [
  { type: 'wiki', label: 'Wiki' },
  { type: 'glossary', label: '词条' },
  { type: 'api', label: 'API 定义' },
]

const API_TYPES: ApiSchemaField['type'][] = ['string', 'number', 'integer', 'boolean', 'array', 'object']

function documentLabel(type: DocumentType) {
  return DOCUMENT_TYPES.find((item) => item.type === type)?.label ?? '文档'
}

function moduleBase(type: DocumentType) {
  return `/documents/${type}`
}

function documentUrl(type: DocumentType, id: string) {
  if (type === 'wiki') return `/documents/wiki/${id}`
  return `/documents/${type}/${type === 'glossary' ? 'term' : 'definition'}/${id}`
}

function directoryUrl(type: Exclude<DocumentType, 'wiki'>, id: string) {
  return `/documents/${type}/directory/${id}`
}

function nodeUrl(type: DocumentType, node: DocumentNode) {
  return node.node_kind === 'directory'
    ? directoryUrl(type as Exclude<DocumentType, 'wiki'>, node.id)
    : documentUrl(type, node.id)
}

function parseNodeFromRoute(type: DocumentType, id: string | undefined, routeNodeKind?: 'document' | 'directory') {
  if (!id) return null
  if (type === 'wiki') return { id, kind: 'document' as const }
  return { id, kind: routeNodeKind === 'directory' ? 'directory' as const : 'document' as const }
}

function NoProject() {
  return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">请先在侧边栏选择当前项目。</CardContent></Card>
}

function treeKey(projectId: string | undefined, module: DocumentType, parentId: string | null) {
  return ['document-tree', projectId, module, parentId]
}

function TreeChildren({
  projectId,
  module,
  parentId,
  expanded,
  onToggle,
  onNavigate,
  selectedId,
  canEdit,
  onMove,
}: {
  projectId: string
  module: DocumentType
  parentId: string | null
  expanded: Set<string>
  onToggle: (id: string) => void
  onNavigate: (url: string) => void
  selectedId?: string
  canEdit: boolean
  onMove: (source: DocumentNode, target: DocumentNode | null) => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: treeKey(projectId, module, parentId),
    queryFn: () => api.get<{ items: DocumentNode[]; next_cursor: string | null }>(`/projects/${projectId}/documents/${module}/children?${parentId ? `parent_id=${parentId}&` : ''}limit=100`),
  })
  if (isLoading) return parentId ? <p className="px-3 py-1 text-xs text-muted-foreground">加载中…</p> : <p className="px-3 py-2 text-sm text-muted-foreground">加载中…</p>
  if (!data?.items.length) return parentId ? null : <p className="px-3 py-2 text-sm text-muted-foreground">暂无内容</p>
  return <div className={parentId ? 'ml-3 border-l pl-1.5' : 'space-y-0.5'}>{data.items.map((node) => (
    <TreeNode key={node.id} node={node} projectId={projectId} module={module} expanded={expanded} onToggle={onToggle} onNavigate={onNavigate} selectedId={selectedId} canEdit={canEdit} onMove={onMove} />
  ))}</div>
}

function TreeNode({
  node,
  projectId,
  module,
  expanded,
  onToggle,
  onNavigate,
  selectedId,
  canEdit,
  onMove,
}: {
  node: DocumentNode
  projectId: string
  module: DocumentType
  expanded: Set<string>
  onToggle: (id: string) => void
  onNavigate: (url: string) => void
  selectedId?: string
  canEdit: boolean
  onMove: (source: DocumentNode, target: DocumentNode | null) => void
}) {
  const open = expanded.has(node.id)
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    const source = JSON.parse(event.dataTransfer.getData('application/x-zeichen-document-node')) as DocumentNode
    if (source.id !== node.id) onMove(source, node)
  }
  return <div onDragOver={canEdit ? (event) => event.preventDefault() : undefined} onDrop={canEdit ? drop : undefined}>
    <div className={`group flex min-w-0 items-center gap-1 rounded-md pr-1 ${selectedId === node.id ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
      {node.has_children ? <button type="button" onClick={() => onToggle(node.id)} aria-label={`${open ? '收起' : '展开'}${node.title}`} className="h-7 w-5 shrink-0 text-xs" aria-expanded={open}>{open ? '⌄' : '›'}</button> : <span className="w-5 shrink-0" />}
      <button
        type="button"
        draggable={canEdit}
        onDragStart={canEdit ? (event) => event.dataTransfer.setData('application/x-zeichen-document-node', JSON.stringify(node)) : undefined}
        onClick={() => onNavigate(nodeUrl(module, node))}
        className="min-w-0 flex-1 truncate py-1.5 text-left text-sm"
        title={node.title}
      >
        {node.title}
      </button>
    </div>
    {node.has_children && open && <TreeChildren projectId={projectId} module={module} parentId={node.id} expanded={expanded} onToggle={onToggle} onNavigate={onNavigate} selectedId={selectedId} canEdit={canEdit} onMove={onMove} />}
  </div>
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
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '重命名失败，请重试')
    } finally { setSubmitting(false) }
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>重命名</DialogTitle><DialogDescription>只会修改当前节点的名称。</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div className="space-y-1.5"><Label htmlFor="node-name">名称</Label><Input id="node-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} required maxLength={256} /></div>{error && <p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="submit" disabled={submitting}>{submitting ? '保存中…' : '保存'}</Button></DialogFooter></form></DialogContent></Dialog>
}

function CreateDirectoryDialog({
  module,
  projectId,
  parentId,
  open,
  onOpenChange,
  onCreated,
}: {
  module: Exclude<DocumentType, 'wiki'>
  projectId: string
  parentId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open) {
      setName('')
      setError(null)
    }
  }, [open])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await api.post(`/projects/${projectId}/documents/${module}/directories`, { name: name.trim(), parent_id: parentId })
      onOpenChange(false)
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建目录失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建目录</DialogTitle>
          <DialogDescription>目录只用于组织当前模块中的条目。</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="directory-name">目录名称</Label>
            <Input id="directory-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} required maxLength={256} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
            <Button type="submit" disabled={submitting}>{submitting ? '创建中…' : '创建目录'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ModuleTreeSidebar({
  module,
  selected,
  selectedNode,
  onNavigate,
}: {
  module: DocumentType
  selected: { id: string; kind: 'document' | 'directory' } | null
  selectedNode: DocumentNode | null
  onNavigate: (url: string) => void
}) {
  const { projectId, currentProject } = useCurrentProject()
  const role = useProjectRole()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const canEdit = role === 'owner' || role === 'editor'
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [deletedOpen, setDeletedOpen] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [createDirectoryOpen, setCreateDirectoryOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteImpact, setDeleteImpact] = useState<{ documents: number; directories: number } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId || !selected) return
    void api.get<{ items: DocumentNode[] }>(`/projects/${projectId}/documents/${module}/ancestors/${selected.kind}/${selected.id}`).then((result) => {
      setExpanded((current) => new Set([...current, ...result.items.slice(0, -1).map((node) => node.id)]))
    }).catch(() => undefined)
  }, [module, projectId, selected?.id, selected?.kind])

  function invalidate() {
    void qc.invalidateQueries({ queryKey: ['document-tree', projectId, module] })
    void qc.invalidateQueries({ queryKey: ['document-node'] })
  }
  function toggle(id: string) { setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next }) }
  function createDocument() {
    const parent = module === 'wiki' ? (selected?.kind === 'document' ? selected.id : null) : (selected?.kind === 'directory' ? selected.id : selectedNode && selectedNode.node_kind === 'document' ? selectedNode.directory_id : null)
    onNavigate(`${moduleBase(module)}?mode=new${parent ? `&container_id=${parent}` : ''}`)
  }
  function createDirectory() {
    if (module !== 'wiki') setCreateDirectoryOpen(true)
  }
  function move(source: DocumentNode, target: DocumentNode | null) {
    if (target?.node_kind === 'document' && module !== 'wiki') {
      setActionError('词条和 API 定义只能移动到目录或模块根')
      return
    }
    const targetId = target?.node_kind === 'directory' || (module === 'wiki' && target?.node_kind === 'document') ? target.id : null
    const path = source.node_kind === 'directory' ? `/directories/${module}/${source.id}/move` : `/documents/${module}/${source.id}/move`
    const body = source.node_kind === 'directory' || module === 'wiki' ? { parent_id: targetId } : { directory_id: targetId }
    void api.post(path, body).then(() => invalidate()).catch((err) => setActionError(err instanceof ApiError ? err.message : '移动失败'))
  }
  async function beginDelete() {
    if (!selectedNode) return
    try {
      const path = selectedNode.node_kind === 'directory' ? `/directories/${module}/${selectedNode.id}/delete-impact` : `/documents/${module}/${selectedNode.id}/delete-impact`
      setDeleteImpact(await api.get(path))
      setDeleteOpen(true)
    } catch (err) { setActionError(err instanceof ApiError ? err.message : '无法获取删除影响范围') }
  }
  async function confirmDelete() {
    if (!selectedNode) return
    try {
      const path = selectedNode.node_kind === 'directory' ? `/directories/${module}/${selectedNode.id}/delete` : `/documents/${module}/${selectedNode.id}/delete`
      await api.post(path)
      setDeleteOpen(false)
      invalidate()
      navigate(moduleBase(module))
    } catch (err) { setActionError(err instanceof ApiError ? err.message : '删除失败') }
  }

  if (!projectId || !currentProject) return null
  return <aside className="flex w-64 shrink-0 flex-col border-r bg-background" aria-label={`${documentLabel(module)}文件组织`}>
    <div className="border-b px-4 py-4"><p className="font-semibold">{documentLabel(module)}</p><p className="mt-1 truncate text-xs text-muted-foreground">{currentProject.name}</p></div>
    <div className="border-b p-3"><Input aria-label="搜索文档（即将支持）" autoComplete="off" placeholder="搜索文档（即将支持）" disabled /></div>
    {canEdit && <div className="flex flex-wrap gap-2 border-b p-3"><Button size="sm" onClick={createDocument}><Plus className="mr-1.5 h-3.5 w-3.5" />新建{module === 'wiki' && selected?.kind === 'document' ? '子 Wiki' : documentLabel(module)}</Button>{module !== 'wiki' && <Button size="sm" variant="outline" onClick={createDirectory}>新建目录</Button>}{selectedNode && <><Button size="sm" variant="ghost" onClick={() => setRenameOpen(true)}>重命名</Button><Button size="sm" variant="ghost" onClick={() => void beginDelete()}>删除</Button></>}</div>}
    <div className="flex items-center justify-between px-3 pt-3"><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">文件组织</p><Button size="xs" variant="ghost" onClick={() => setDeletedOpen((value) => !value)}>{deletedOpen ? '返回树' : '已删除'}</Button></div>
    <div className="flex-1 overflow-y-auto p-3" onDragOver={canEdit ? (event) => event.preventDefault() : undefined} onDrop={canEdit ? (event) => { const source = JSON.parse(event.dataTransfer.getData('application/x-zeichen-document-node')) as DocumentNode; move(source, null) } : undefined}>
      {deletedOpen ? <DeletedNodes projectId={projectId} module={module} canEdit={canEdit} onChanged={invalidate} /> : <TreeChildren projectId={projectId} module={module} parentId={null} expanded={expanded} onToggle={toggle} onNavigate={onNavigate} selectedId={selected?.id} canEdit={canEdit} onMove={move} />}
    </div>
    <ErrorNotification message={actionError} />
    <RenameDialog node={selectedNode} module={module} open={renameOpen} onOpenChange={setRenameOpen} onSaved={invalidate} />
    {module !== 'wiki' && <CreateDirectoryDialog module={module} projectId={projectId} parentId={selected?.kind === 'directory' ? selected.id : selectedNode?.node_kind === 'document' ? selectedNode.directory_id : null} open={createDirectoryOpen} onOpenChange={setCreateDirectoryOpen} onCreated={invalidate} />}
    <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>确认删除</DialogTitle><DialogDescription>将递归软删除 {deleteImpact?.directories ?? 0} 个目录和 {deleteImpact?.documents ?? 0} 篇文档；引用会保留并标记为已删除。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void confirmDelete()}>删除</Button></DialogFooter></DialogContent></Dialog>
  </aside>
}

function DeletedNodes({ projectId, module, canEdit, onChanged }: { projectId: string; module: DocumentType; canEdit: boolean; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const { data, isLoading } = useQuery({ queryKey: ['document-deleted', projectId, module], queryFn: () => api.get<{ items: DocumentNode[] }>(`/projects/${projectId}/documents/${module}/deleted?limit=100`) })
  async function restore(node: DocumentNode) {
    try {
      const path = node.node_kind === 'directory' ? `/directories/${module}/${node.id}/restore` : `/documents/${module}/${node.id}/restore`
      await api.post(path)
      onChanged()
    } catch (err) { setError(err instanceof ApiError ? err.message : '恢复失败') }
  }
  return <div className="space-y-1">{isLoading ? <p className="text-sm text-muted-foreground">加载中…</p> : data?.items.map((node) => <div key={node.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm text-muted-foreground"><span className="min-w-0 flex-1 truncate">{node.title}</span>{canEdit && <Button size="xs" variant="outline" onClick={() => void restore(node)}>恢复</Button>}</div>)}<ErrorNotification message={error} /></div>
}

function DocumentEditor({
  module,
  document,
  containerId,
  onDirtyChange,
  onRegisterSave,
  onSaved,
  onCancel,
}: {
  module: DocumentType
  document?: DocumentRow
  containerId: string | null
  onDirtyChange: (dirty: boolean) => void
  onRegisterSave: (save: () => Promise<boolean>) => void
  onSaved: (document: DocumentRow) => void
  onCancel: () => void
}) {
  const { projectId } = useCurrentProject()
  const [title, setTitle] = useState(document?.title ?? '')
  const [content, setContent] = useState(document?.content ?? '')
  const [method, setMethod] = useState(document?.metadata.endpoint?.method ?? 'GET')
  const [path, setPath] = useState(document?.metadata.endpoint?.path ?? '/')
  const [fields, setFields] = useState<ApiSchemaField[]>(document?.metadata.schema?.fields ?? [])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dirty, setDirty] = useState(false)
  function markDirty() { setDirty(true); onDirtyChange(true) }
  useEffect(() => () => onDirtyChange(false), [onDirtyChange])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  async function save(stayOnPage = false): Promise<boolean> {
    setError(null)
    setSubmitting(true)
    const metadata = module === 'api' ? { endpoint: { method, path }, schema: { fields } } : {}
    try {
      const saved = document
        ? await api.patch<DocumentRow>(`/documents/${module}/${document.id}`, { title: title.trim(), content, metadata })
        : await api.post<DocumentRow>(`/projects/${projectId}/documents/${module}`, { title: title.trim(), doc_type: module, content, metadata, ...(module === 'wiki' ? { parent_id: containerId } : { directory_id: containerId }) })
      setDirty(false)
      onDirtyChange(false)
      if (!stayOnPage) onSaved(saved)
      return true
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败，请重试')
      return false
    } finally { setSubmitting(false) }
  }
  useEffect(() => { onRegisterSave(() => save(true)) }, [title, content, method, path, fields, document?.id, containerId])
  function changeField(index: number, patch: Partial<ApiSchemaField>) { setFields((current) => current.map((field, i) => i === index ? { ...field, ...patch } : field)); markDirty() }
  const status = dirty ? '未保存的更改' : document ? '已保存' : '尚未创建'
  return <form onSubmit={(event) => { event.preventDefault(); void save() }} className="flex min-w-0 flex-1 flex-col"><ErrorNotification message={error} />
    <header className="border-b bg-background"><div className="mx-auto flex min-h-14 w-full max-w-5xl items-center justify-between gap-3 px-5 sm:px-8"><div className="flex min-w-0 items-center gap-3"><Button type="button" size="sm" variant="ghost" onClick={onCancel}>返回</Button><span className="hidden h-4 border-l sm:block" /><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{documentLabel(module)}</span><span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex"><span className={`h-1.5 w-1.5 rounded-full ${dirty ? 'bg-amber-500' : 'bg-emerald-500'}`} />{status}</span></div><div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" onClick={onCancel}>取消</Button><Button type="submit" size="sm" disabled={submitting}>{submitting ? '保存中…' : '保存版本'}</Button></div></div></header>
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-9 sm:px-8 sm:py-12"><div className="mx-auto flex w-full max-w-3xl flex-1 flex-col"><h1 className="sr-only">{document ? `编辑${document.title}` : `新建${documentLabel(module)}`}</h1><div className="space-y-2"><Label htmlFor="document-title" className="sr-only">标题</Label><Input id="document-title" autoComplete="off" value={title} onChange={(event) => { setTitle(event.target.value); markDirty() }} maxLength={256} required placeholder={module === 'glossary' ? '输入词条名称' : '输入文档标题'} className="h-auto rounded-none border-0 px-0 py-0 text-3xl font-semibold tracking-tight shadow-none placeholder:text-muted-foreground/60 focus-visible:ring-0 sm:text-4xl" /><p className="text-sm text-muted-foreground">保存会创建一个新的版本。</p></div>
      {module === 'api' && <section className="mt-8 space-y-4 rounded-xl border bg-muted/20 p-4 sm:p-5"><div><h2 className="font-medium">接口定义</h2><p className="mt-1 text-sm text-muted-foreground">端点和 Schema 会随正文一起保存为同一版本。</p></div><div className="grid gap-3 sm:grid-cols-[140px_1fr]"><div className="space-y-1.5"><Label htmlFor="api-method">方法</Label><Input id="api-method" autoComplete="off" value={method} onChange={(event) => { setMethod(event.target.value.toUpperCase()); markDirty() }} required /></div><div className="space-y-1.5"><Label htmlFor="api-path">路径</Label><Input id="api-path" autoComplete="off" value={path} onChange={(event) => { setPath(event.target.value); markDirty() }} required /></div></div><div className="space-y-2"><div className="flex items-center justify-between"><Label>Schema 字段</Label><Button type="button" size="sm" variant="outline" onClick={() => { setFields((current) => [...current, { name: '', type: 'string' }]); markDirty() }}>添加字段</Button></div>{fields.map((field, index) => <div key={index} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_130px_auto_auto]"><Input aria-label={`字段名 ${index + 1}`} autoComplete="off" value={field.name} onChange={(event) => changeField(index, { name: event.target.value })} placeholder="字段名" required /><select aria-label={`字段类型 ${index + 1}`} value={field.type} onChange={(event) => changeField(index, { type: event.target.value as ApiSchemaField['type'] })} className="h-8 rounded-lg border bg-background px-2 text-sm">{API_TYPES.map((item) => <option key={item}>{item}</option>)}</select><label className="flex h-8 items-center gap-1.5 text-sm"><input type="checkbox" autoComplete="off" checked={Boolean(field.required)} onChange={(event) => changeField(index, { required: event.target.checked })} />必填</label><Button type="button" size="sm" variant="ghost" onClick={() => { setFields((current) => current.filter((_, i) => i !== index)); markDirty() }}>移除</Button></div>)}</div></section>}
      <section className="mt-9 flex min-h-[34rem] flex-1 flex-col border-t pt-5"><div className="mb-3 flex items-center justify-between"><Label id="document-content-label">正文</Label><span id="document-content-hint" className="text-xs text-muted-foreground">Markdown 即时渲染</span></div><div className="min-h-[30rem] flex-1"><VditorIrEditor initialMarkdown={content} onChange={(markdown) => { setContent(markdown); markDirty() }} disabled={submitting} ariaLabelledBy="document-content-label" ariaDescribedBy="document-content-hint" /></div></section></div></main>
  </form>
}

function DocumentDetail({ module, document, onEdit }: { module: DocumentType; document: DocumentRow; onEdit: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const role = useProjectRole()
  const canEdit = role === 'owner' || role === 'editor'
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteImpact, setDeleteImpact] = useState<{ documents: number; directories: number } | null>(null)
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data: versions } = useQuery({ queryKey: ['document-versions', module, document.id], queryFn: () => api.get<{ items: DocumentVersionRow[] }>(`/documents/${module}/${document.id}/versions`), enabled: versionsOpen })
  const { data: references } = useQuery({ queryKey: ['document-references', module, document.id], queryFn: () => api.get<{ count: number; items: ReferenceRow[] }>(`/documents/${module}/${document.id}/references`) })
  async function rollback(versionNo: number) { try { await api.post(`/documents/${module}/${document.id}/rollback`, { version_no: versionNo }); setRollbackTarget(null); setVersionsOpen(false); await qc.invalidateQueries({ queryKey: ['document-node'] }); await qc.invalidateQueries({ queryKey: ['document-versions', module, document.id] }) } catch (err) { setError(err instanceof ApiError ? err.message : '回滚失败') } }
  async function beginDelete() {
    try {
      setDeleteImpact(await api.get(`/documents/${module}/${document.id}/delete-impact`))
      setDeleteOpen(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '无法获取删除影响范围')
    }
  }
  async function remove() { try { await api.post(`/documents/${module}/${document.id}/delete`); navigate(moduleBase(module)); } catch (err) { setError(err instanceof ApiError ? err.message : '删除失败') } }
  return <main className="mx-auto w-full max-w-5xl px-6 py-10 sm:px-10"><div className="mx-auto max-w-3xl"><div className="flex flex-wrap items-start justify-between gap-4 border-b pb-5"><div><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{documentLabel(module)}</span><h1 className="mt-4 text-3xl font-semibold tracking-tight">{document.title}</h1><p className="mt-2 text-sm text-muted-foreground">更新于 {new Date(document.updated_at).toLocaleString()}</p></div>{canEdit && <div className="flex gap-2"><Button variant="outline" onClick={() => setVersionsOpen(true)}><History className="mr-2 h-4 w-4" />版本</Button><Button variant="outline" onClick={onEdit}>编辑</Button><Button variant="destructive" onClick={() => void beginDelete()}><Trash2 className="mr-2 h-4 w-4" />删除</Button></div>}</div>
    {module === 'api' && <section className="mt-7 rounded-xl border bg-muted/20 p-5"><h2 className="font-medium">{document.metadata.endpoint?.method} {document.metadata.endpoint?.path}</h2><div className="mt-4 space-y-2">{(document.metadata.schema?.fields ?? []).map((field) => <div key={field.name} className="flex gap-3 text-sm"><code>{field.name}</code><span className="text-muted-foreground">{field.type}</span>{field.required && <span className="text-destructive">必填</span>}</div>)}</div></section>}
    <section className="mt-8"><VditorMarkdownViewer markdown={document.content ?? ''} /></section><section className="mt-8 rounded-xl border p-5"><h2 className="font-medium">引用</h2><div className="mt-3 space-y-2 text-sm">{references?.items.length ? references.items.map((reference) => <p key={reference.id}>{reference.from_id === document.id ? '引用了' : '被引用于'} {reference.from_id === document.id ? reference.to_type : reference.from_type}:{(reference.from_id === document.id ? reference.to_id : reference.from_id).slice(0, 8)}</p>) : <p className="text-muted-foreground">暂无引用</p>}</div></section></div><ErrorNotification message={error} />
    <Dialog open={versionsOpen} onOpenChange={setVersionsOpen}><DialogContent><DialogHeader><DialogTitle>版本历史</DialogTitle><DialogDescription>回滚会复制历史快照并创建新版本。</DialogDescription></DialogHeader><div className="max-h-96 space-y-2 overflow-y-auto">{versions?.items.map((version) => <div key={version.id} className="flex items-center justify-between rounded border p-3 text-sm"><span>版本 {version.version_no} · {version.title}</span>{canEdit && <Button size="sm" variant="outline" onClick={() => setRollbackTarget(version.version_no)}><RotateCcw className="mr-1.5 h-3.5 w-3.5" />回滚</Button>}</div>)}</div></DialogContent></Dialog>
    <Dialog open={rollbackTarget !== null} onOpenChange={(open) => !open && setRollbackTarget(null)}><DialogContent><DialogHeader><DialogTitle>确认回滚</DialogTitle><DialogDescription>标题、正文与 API metadata 会一同恢复，并额外创建新版本。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setRollbackTarget(null)}>取消</Button><Button onClick={() => rollbackTarget !== null && void rollback(rollbackTarget)}>确认回滚</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>删除文档</DialogTitle><DialogDescription>将软删除 {deleteImpact?.documents ?? 0} 篇文档和 {deleteImpact?.directories ?? 0} 个目录；Wiki 会递归删除其子树，引用会保留并标记为已删除。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void remove()}>确认删除</Button></DialogFooter></DialogContent></Dialog>
  </main>
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
  const { data: directory } = useQuery({ queryKey: ['directory-node', module, selected?.id], queryFn: () => api.get<DocumentDirectoryRow>(`/directories/${module}/${selected?.id}`), enabled: selected?.kind === 'directory' && module !== 'wiki' })
  const canEdit = role === 'owner' || role === 'editor'
  function requestNavigation(url: string) { if (dirty) setPendingUrl(url); else navigate(url) }
  async function saveAndNavigate() { if (pendingUrl && await saveRef.current()) { const target = pendingUrl; setPendingUrl(null); navigate(target) } }
  useEffect(() => {
    registerBlocker((target) => {
      if (!dirty) return false
      setPendingUrl(target)
      return true
    })
    return () => registerBlocker(null)
  }, [dirty, registerBlocker])
  if (loadingProject) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <NoProject />
  if (documentError) return <ErrorNotification message={(documentError as Error).message} />
  const editing = mode === 'new' || mode === 'edit'
  return <div className="-m-6 flex min-h-[calc(100vh-0.5px)] bg-background"><ModuleTreeSidebar module={module} selected={selected} selectedNode={document ?? directory ?? null} onNavigate={requestNavigation} />
    {documentLoading ? <p className="p-8 text-sm text-muted-foreground">加载中…</p> : mode === 'new' && canEdit ? <DocumentEditor key={`new-${module}-${containerId ?? 'root'}`} module={module} containerId={containerId} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(module, saved.id))} onCancel={() => requestNavigation(moduleBase(module))} /> : document && editing && canEdit ? <DocumentEditor key={document.id} module={module} document={document} containerId={document.parent_id ?? document.directory_id} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(module, saved.id))} onCancel={() => requestNavigation(documentUrl(module, document.id))} /> : document ? <DocumentDetail module={module} document={document} onEdit={() => navigate(`${documentUrl(module, document.id)}?mode=edit`)} /> : directory ? <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">{directory.name}</h1><p className="mt-2 text-sm text-muted-foreground">在左侧目录中选择条目，或新建文档。</p></div></main> : <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">{documentLabel(module)}</h1><p className="mt-2 text-sm text-muted-foreground">从左侧浏览文件组织，或新建文档。</p></div></main>}
    <Dialog open={pendingUrl !== null} onOpenChange={(open) => !open && setPendingUrl(null)}><DialogContent><DialogHeader><DialogTitle>未保存的更改</DialogTitle><DialogDescription>切换前请选择如何处理当前文档。</DialogDescription></DialogHeader><DialogFooter className="sm:justify-between"><Button variant="ghost" onClick={() => setPendingUrl(null)}>留在当前文档</Button><div className="flex gap-2"><Button variant="outline" onClick={() => { const target = pendingUrl; setDirty(false); setPendingUrl(null); if (target) navigate(target) }}>放弃更改并切换</Button><Button onClick={() => void saveAndNavigate()}>保存并切换</Button></div></DialogFooter></DialogContent></Dialog>
  </div>
}
