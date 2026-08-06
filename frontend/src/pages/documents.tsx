import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, History, MoreHorizontal, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { VditorIrEditor, VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ErrorNotification } from '@/components/ui/notification'
import { ApiCodeTreeSidebar } from '@/components/api-code-tree'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, ApiError, type DocumentDirectoryRow, type DocumentNode, type DocumentRow, type DocumentType, type DocumentVersionRow, type LibrarySymbol, type LibrarySymbolException, type LibrarySymbolKind, type LibrarySymbolOption, type LibrarySymbolParameter, type ReferenceRow } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { useDocumentNavigation } from '@/lib/document-navigation'

export const DOCUMENT_TYPES: { type: DocumentType; label: string }[] = [
  { type: 'wiki', label: 'Wiki' },
  { type: 'glossary', label: '词条' },
  { type: 'api', label: '程序库 API' },
]

const LIBRARY_SYMBOL_KINDS: { value: LibrarySymbolKind; label: string }[] = [
  { value: 'class', label: '类' }, { value: 'struct', label: '结构体' }, { value: 'interface', label: '接口' }, { value: 'enum', label: '枚举' },
  { value: 'function', label: '函数' }, { value: 'constructor', label: '构造函数' }, { value: 'method', label: '方法' }, { value: 'field', label: '字段' }, { value: 'property', label: '属性' }, { value: 'constant', label: '常量' }, { value: 'enum_value', label: '枚举值' },
]

const CALLABLE_KINDS: LibrarySymbolKind[] = ['function', 'constructor', 'method']

function emptyLibrarySymbol(): LibrarySymbol {
  return { language: 'C#', package: '', namespace: '', symbol: '', kind: 'function', visibility: 'public', canonical_signature: '', return_type: '', return_description: '', since_version: '', deprecated: false, parameters: [], exceptions: [] }
}

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
  onRename,
  onDelete,
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
  onRename: (node: DocumentNode) => void
  onDelete: (node: DocumentNode) => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: treeKey(projectId, module, parentId),
    queryFn: () => api.get<{ items: DocumentNode[]; next_cursor: string | null }>(`/projects/${projectId}/documents/${module}/children?${parentId ? `parent_id=${parentId}&` : ''}limit=100`),
  })
  if (isLoading) return parentId ? <p className="px-3 py-1 text-xs text-muted-foreground">加载中…</p> : <p className="px-3 py-2 text-sm text-muted-foreground">加载中…</p>
  if (!data?.items.length) return parentId ? null : <p className="px-3 py-2 text-sm text-muted-foreground">暂无内容</p>
  return <div className={parentId ? 'ml-3 border-l pl-1.5' : 'space-y-0.5'}>{data.items.map((node) => (
    <TreeNode key={node.id} node={node} projectId={projectId} module={module} expanded={expanded} onToggle={onToggle} onNavigate={onNavigate} selectedId={selectedId} canEdit={canEdit} onMove={onMove} onRename={onRename} onDelete={onDelete} />
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
  onRename,
  onDelete,
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
  onRename: (node: DocumentNode) => void
  onDelete: (node: DocumentNode) => void
}) {
  const open = expanded.has(node.id)
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    const source = JSON.parse(event.dataTransfer.getData('application/x-zeichen-document-node')) as DocumentNode
    if (source.id !== node.id) onMove(source, node)
  }
  return <div onDragOver={canEdit ? (event) => event.preventDefault() : undefined} onDrop={canEdit ? drop : undefined}>
    <div className={`group flex min-w-0 items-center gap-1 rounded-md pr-1 ${selectedId === node.id ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
      {node.has_children ? <button type="button" onClick={() => onToggle(node.id)} aria-label={`${open ? '收起' : '展开'}${node.title}`} className="flex h-7 w-5 shrink-0 items-center justify-center" aria-expanded={open}>{open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</button> : <span className="w-5 shrink-0" />}
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
      {canEdit && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onClick={() => onRename(node)}><Pencil />重命名</DropdownMenuItem><DropdownMenuItem variant="destructive" onClick={() => onDelete(node)}><Trash2 />删除</DropdownMenuItem></DropdownMenuContent></DropdownMenu>}
    </div>
    {node.has_children && open && <TreeChildren projectId={projectId} module={module} parentId={node.id} expanded={expanded} onToggle={onToggle} onNavigate={onNavigate} selectedId={selectedId} canEdit={canEdit} onMove={onMove} onRename={onRename} onDelete={onDelete} />}
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
  const [actionNode, setActionNode] = useState<DocumentNode | null>(null)
  const [deleteImpact, setDeleteImpact] = useState<{ documents: number; directories: number } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId || !selected) return
    void api.get<{ items: DocumentNode[] }>(`/projects/${projectId}/documents/${module}/ancestors/${selected.kind}/${selected.id}`).then((result) => {
      setExpanded((current) => new Set([...current, ...result.items.slice(0, -1).map((node) => node.id)]))
    }).catch(() => undefined)
  }, [module, projectId, selected?.id, selected?.kind])

  async function invalidate() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['document-tree', projectId, module] }),
      qc.invalidateQueries({ queryKey: ['document-node'] }),
    ])
  }
  function toggle(id: string) { setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next }) }
  function createDocument(parentId?: string | null) {
    const parent = parentId === undefined ? (module === 'wiki' ? (selected?.kind === 'document' ? selected.id : null) : (selected?.kind === 'directory' ? selected.id : selectedNode && selectedNode.node_kind === 'document' ? selectedNode.directory_id : null)) : parentId
    onNavigate(`${moduleBase(module)}?mode=new${parent ? `&container_id=${parent}` : ''}`)
  }
  function createRootDocument() { createDocument(null) }
  function createDirectory() {
    if (module !== 'wiki') setCreateDirectoryOpen(true)
  }
  function move(source: DocumentNode, target: DocumentNode | null) {
    if (target?.node_kind === 'document' && module !== 'wiki') {
      setActionError('词条和程序库 API 只能移动到目录或模块根')
      return
    }
    const targetId = target?.node_kind === 'directory' || (module === 'wiki' && target?.node_kind === 'document') ? target.id : null
    const path = source.node_kind === 'directory' ? `/directories/${module}/${source.id}/move` : `/documents/${module}/${source.id}/move`
    const body = source.node_kind === 'directory' || module === 'wiki' ? { parent_id: targetId } : { directory_id: targetId }
    void api.post(path, body).then(() => invalidate()).catch((err) => setActionError(err instanceof ApiError ? err.message : '移动失败'))
  }
  async function beginDelete(node: DocumentNode) {
    try {
      const path = node.node_kind === 'directory' ? `/directories/${module}/${node.id}/delete-impact` : `/documents/${module}/${node.id}/delete-impact`
      setDeleteImpact(await api.get(path))
      setActionNode(node)
      setDeleteOpen(true)
    } catch (err) { setActionError(err instanceof ApiError ? err.message : '无法获取删除影响范围') }
  }
  async function confirmDelete() {
    if (!actionNode) return
    try {
      const path = actionNode.node_kind === 'directory' ? `/directories/${module}/${actionNode.id}/delete` : `/documents/${module}/${actionNode.id}/delete`
      await api.post(path)
      setDeleteOpen(false)
      await invalidate()
      navigate(moduleBase(module))
    } catch (err) { setActionError(err instanceof ApiError ? err.message : '删除失败') }
  }

  if (!projectId || !currentProject) return null
  if (module === 'api') return <ApiCodeTreeSidebar projectId={projectId} projectName={currentProject.name} selectedId={selected?.kind === 'document' ? selected.id : undefined} canEdit={canEdit} onNavigate={onNavigate} />
  return <aside className="flex w-64 shrink-0 flex-col border-r bg-background" aria-label={`${documentLabel(module)}文件组织`}>
    <div className="border-b px-4 py-4"><p className="font-semibold">{documentLabel(module)}</p><p className="mt-1 truncate text-xs text-muted-foreground">{currentProject.name}</p></div>
    <div className="border-b p-3"><Input aria-label="搜索文档（即将支持）" autoComplete="off" placeholder="搜索文档（即将支持）" disabled /></div>
    {canEdit && <div className="flex justify-end border-b p-3"><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-sm" variant="default" aria-label="新建"><Plus className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-36">{module === 'wiki' ? <><DropdownMenuItem onClick={createRootDocument}>新建 Wiki</DropdownMenuItem>{selected?.kind === 'document' && <DropdownMenuItem onClick={() => createDocument(selected.id)}>新建子 Wiki</DropdownMenuItem>}</> : <><DropdownMenuItem onClick={() => createDocument()}>新建{documentLabel(module)}</DropdownMenuItem><DropdownMenuItem onClick={createDirectory}>新建目录</DropdownMenuItem></>}</DropdownMenuContent></DropdownMenu></div>}
    <div className="flex items-center justify-between px-3 pt-3"><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">文件组织</p><Button size="xs" variant="ghost" onClick={() => setDeletedOpen((value) => !value)}>{deletedOpen ? '返回树' : '已删除'}</Button></div>
    <div className="flex-1 overflow-y-auto p-3" onDragOver={canEdit ? (event) => event.preventDefault() : undefined} onDrop={canEdit ? (event) => { const source = JSON.parse(event.dataTransfer.getData('application/x-zeichen-document-node')) as DocumentNode; move(source, null) } : undefined}>
      {deletedOpen ? <DeletedNodes projectId={projectId} module={module} canEdit={canEdit} onChanged={invalidate} /> : <TreeChildren projectId={projectId} module={module} parentId={null} expanded={expanded} onToggle={toggle} onNavigate={onNavigate} selectedId={selected?.id} canEdit={canEdit} onMove={move} onRename={(node) => { setActionNode(node); setRenameOpen(true) }} onDelete={(node) => void beginDelete(node)} />}
    </div>
    <ErrorNotification message={actionError} />
    <RenameDialog node={actionNode} module={module} open={renameOpen} onOpenChange={setRenameOpen} onSaved={invalidate} />
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
  ownerSymbolId,
  librarySymbolKind,
  libraryLocation,
  onDirtyChange,
  onRegisterSave,
  onSaved,
  onCancel,
}: {
  module: DocumentType
  document?: DocumentRow
  containerId: string | null
  ownerSymbolId?: string | null
  librarySymbolKind?: LibrarySymbolKind | null
  libraryLocation?: { language: string | null; package: string | null; namespace: string | null }
  onDirtyChange: (dirty: boolean) => void
  onRegisterSave: (save: () => Promise<boolean>) => void
  onSaved: (document: DocumentRow) => void
  onCancel: () => void
}) {
  const { projectId } = useCurrentProject()
  const qc = useQueryClient()
  const [title, setTitle] = useState(document?.title ?? '')
  const [content, setContent] = useState(document?.content ?? '')
  const [librarySymbol, setLibrarySymbol] = useState<LibrarySymbol>(() => ({ ...(document?.library_symbol ?? emptyLibrarySymbol()), owner_symbol_id: document?.library_symbol?.owner_symbol_id ?? ownerSymbolId ?? null, kind: document?.library_symbol?.kind ?? librarySymbolKind ?? emptyLibrarySymbol().kind, language: document?.library_symbol?.language ?? libraryLocation?.language ?? emptyLibrarySymbol().language, package: document?.library_symbol?.package ?? libraryLocation?.package ?? '', namespace: document?.library_symbol?.namespace ?? libraryLocation?.namespace ?? '' }))
  const isNestedSymbol = module === 'api' && Boolean(librarySymbol.owner_symbol_id)
  const isConstructor = librarySymbol.kind === 'constructor'
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dirty, setDirty] = useState(false)
  const { data: symbolOptions } = useQuery({
    queryKey: ['library-symbol-options', projectId],
    queryFn: () => api.get<{ items: LibrarySymbolOption[] }>(`/projects/${projectId}/libraries/symbols`),
    enabled: module === 'api' && Boolean(projectId),
  })
  const ownerSymbolName = document?.library_symbol?.owner_symbol?.symbol ?? symbolOptions?.items.find((item) => item.id === librarySymbol.owner_symbol_id)?.symbol
  const constructorName = ownerSymbolName ?? librarySymbol.symbol
  function markDirty() { setDirty(true); onDirtyChange(true) }
  function patchLibrarySymbol(patch: Partial<LibrarySymbol>) {
    setLibrarySymbol((current) => ({ ...current, ...patch }))
    if (module === 'api' && patch.symbol !== undefined) setTitle(patch.symbol)
    markDirty()
  }
  function patchTitle(value: string) {
    setTitle(value)
    if (module === 'api') setLibrarySymbol((current) => ({ ...current, symbol: value }))
    markDirty()
  }
  function changeParameter(index: number, patch: Partial<LibrarySymbolParameter>) { setLibrarySymbol((current) => ({ ...current, parameters: current.parameters.map((parameter, i) => i === index ? { ...parameter, ...patch } : parameter) })); markDirty() }
  function changeException(index: number, patch: Partial<LibrarySymbolException>) { setLibrarySymbol((current) => ({ ...current, exceptions: current.exceptions.map((exception, i) => i === index ? { ...exception, ...patch } : exception) })); markDirty() }
  useEffect(() => () => onDirtyChange(false), [onDirtyChange])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    if (document || !ownerSymbolId) return
    const owner = symbolOptions?.items.find((item) => item.id === ownerSymbolId)
    if (!owner) return
    setLibrarySymbol((current) => ({
      ...current,
      owner_symbol_id: owner.id,
      language: owner.language,
      package: owner.package,
      namespace: owner.namespace ?? '',
      kind: librarySymbolKind ?? (owner.kind === 'enum' ? 'enum_value' : 'method'),
      symbol: librarySymbolKind === 'constructor' ? owner.symbol : current.symbol,
    }))
    if (librarySymbolKind === 'constructor') setTitle(owner.symbol)
  }, [document, librarySymbol.owner_symbol_id, librarySymbolKind, ownerSymbolId, symbolOptions])

  async function save(stayOnPage = false): Promise<boolean> {
    setError(null)
    setSubmitting(true)
    const apiName = (isConstructor ? constructorName : librarySymbol.symbol.trim() || title.trim()) || '未命名 API'
    const { language, package: packageName, namespace, return_type, return_description, ...symbolFields } = librarySymbol
    const symbolPayload = isNestedSymbol
      ? { ...symbolFields, ...(isConstructor ? {} : { return_type, return_description }), symbol: apiName }
      : { ...symbolFields, language, package: packageName, namespace, ...(isConstructor ? {} : { return_type, return_description }), symbol: apiName }
    const documentTitle = isConstructor
      ? `${apiName}.ctor${librarySymbol.canonical_signature.trim() ? ` — ${librarySymbol.canonical_signature.trim()}` : ''}`
      : apiName
    const payload = { title: module === 'api' ? documentTitle : title.trim(), content, ...(module === 'api' ? { library_symbol: symbolPayload } : {}) }
    try {
      const saved = document
        ? await api.patch<DocumentRow>(`/documents/${module}/${document.id}`, payload)
        : await api.post<DocumentRow>(`/projects/${projectId}/documents/${module}`, { ...payload, doc_type: module, ...(module === 'wiki' ? { parent_id: containerId } : { directory_id: containerId }) })
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['document-tree', projectId, module] }),
        qc.invalidateQueries({ queryKey: ['api-code-tree', projectId] }),
        qc.invalidateQueries({ queryKey: ['library-symbol-options', projectId] }),
        qc.invalidateQueries({ queryKey: ['document-node', module, saved.id] }),
      ])
      setDirty(false)
      onDirtyChange(false)
      if (!stayOnPage) onSaved(saved)
      return true
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败，请重试')
      return false
    } finally { setSubmitting(false) }
  }
  useEffect(() => { onRegisterSave(() => save(true)) }, [title, content, librarySymbol, document?.id, containerId])
  const status = dirty ? '未保存的更改' : document ? '已保存' : '尚未创建'
  const canvasBreadcrumb = document
    ? `${documentLabel(module)} / ${document.title || '未命名文档'}`
    : `${documentLabel(module)} / 新建文档`
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex min-w-0 flex-1 flex-col"
    >
      <ErrorNotification message={error} />
      <header className="border-b bg-background">
        <div className="mx-auto flex min-h-14 w-full max-w-5xl items-center justify-between gap-3 px-5 sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
              {documentLabel(module)}
            </span>
            <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
              <span
                className={`h-1.5 w-1.5 rounded-full ${dirty ? "bg-amber-500" : "bg-emerald-500"}`}
              />
              {status}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onCancel}
            >
              取消
            </Button>
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </header>
      {isConstructor && (
        <style>{`#library-symbol, #library-return-type, #library-return-description { display: none; } div:has(> label[for="library-symbol"]), div:has(> label[for="library-return-type"]), div:has(> label[for="library-return-description"]) { display: none; }`}</style>
      )}
      <main className="flex flex-1 flex-col bg-muted/30">
        <article
          data-testid="document-writing-canvas"
          className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-8 sm:px-10 sm:py-10"
        >
          <h1 className="sr-only">
            {document
              ? `编辑${document.title}`
              : `新建${documentLabel(module)}`}
          </h1>
          <div className="text-xs text-muted-foreground">
            {canvasBreadcrumb}
          </div>
          <div className="mt-5">
            {isConstructor ? (
              <h2 className="text-[2.5rem] font-semibold leading-tight tracking-[-0.045em] md:text-5xl">
                {constructorName || "构造函数"}
              </h2>
            ) : (
              <>
                <Label htmlFor="document-title" className="sr-only">
                  标题
                </Label>
                <Input
                  id="document-title"
                  autoComplete="off"
                  value={title}
                  onChange={(event) => patchTitle(event.target.value)}
                  maxLength={256}
                  placeholder="无标题"
                  className="h-auto rounded-none border-0 bg-transparent px-0 py-0 text-[2.5rem] font-semibold leading-tight tracking-[-0.045em] shadow-none placeholder:text-muted-foreground/55 focus-visible:ring-0 md:!text-5xl"
                />
              </>
            )}
          </div>
          {module === "api" && (
            <section className="mt-5 space-y-5 rounded-xl border bg-muted/20 p-4 sm:p-5">
              <h2 className="font-medium">程序库符号</h2>
              {isNestedSymbol && (
                <p className="text-sm text-muted-foreground">
                  语言、包和命名空间由所属代码结构继承。
                </p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {!isNestedSymbol && (
                  <>
                    <div className="space-y-1.5">
                      <Label htmlFor="library-language">语言</Label>
                      <Input
                        id="library-language"
                        autoComplete="off"
                        value={librarySymbol.language}
                        onChange={(event) =>
                          patchLibrarySymbol({ language: event.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="library-package">包或模块</Label>
                      <Input
                        id="library-package"
                        autoComplete="off"
                        value={librarySymbol.package}
                        onChange={(event) =>
                          patchLibrarySymbol({ package: event.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="library-namespace">命名空间</Label>
                      <Input
                        id="library-namespace"
                        autoComplete="off"
                        value={librarySymbol.namespace ?? ""}
                        onChange={(event) =>
                          patchLibrarySymbol({ namespace: event.target.value })
                        }
                      />
                    </div>
                  </>
                )}
                <div className="space-y-1.5">
                  <Label htmlFor="library-kind">种类</Label>
                  {isNestedSymbol ? (
                    <p
                      id="library-kind"
                      className="flex h-8 items-center rounded-lg border bg-muted px-2 text-sm"
                    >
                      {
                        LIBRARY_SYMBOL_KINDS.find(
                          (kind) => kind.value === librarySymbol.kind,
                        )?.label
                      }
                    </p>
                  ) : (
                    <select
                      id="library-kind"
                      value={librarySymbol.kind}
                      onChange={(event) =>
                        patchLibrarySymbol({
                          kind: event.target.value as LibrarySymbolKind,
                        })
                      }
                      className="h-8 w-full rounded-lg border bg-background px-2 text-sm"
                    >
                      {LIBRARY_SYMBOL_KINDS.map((kind) => (
                        <option key={kind.value} value={kind.value}>
                          {kind.label}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="library-symbol">符号名</Label>
                  <Input
                    id="library-symbol"
                    autoComplete="off"
                    value={librarySymbol.symbol}
                    onChange={(event) =>
                      patchLibrarySymbol({ symbol: event.target.value })
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="library-visibility">可见性</Label>
                  <Input
                    id="library-visibility"
                    autoComplete="off"
                    value={librarySymbol.visibility ?? ""}
                    onChange={(event) =>
                      patchLibrarySymbol({ visibility: event.target.value })
                    }
                    placeholder="public"
                  />
                </div>
                {["field", "property", "constant"].includes(librarySymbol.kind) && (
                  <div className="space-y-1.5">
                    <Label htmlFor="library-value-type">类型</Label>
                    <Input
                      id="library-value-type"
                      autoComplete="off"
                      value={librarySymbol.return_type ?? ""}
                      onChange={(event) =>
                        patchLibrarySymbol({ return_type: event.target.value })
                      }
                      placeholder="例如：float、string 或 Vector3"
                    />
                  </div>
                )}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="library-signature">原始代码签名</Label>
                <Input
                  id="library-signature"
                  autoComplete="off"
                  value={librarySymbol.canonical_signature}
                  onChange={(event) =>
                    patchLibrarySymbol({
                      canonical_signature: event.target.value,
                    })
                  }
                  placeholder="Task&lt;T&gt; LoadAsync&lt;T&gt;(AssetId id)"
                />
              </div>
              {CALLABLE_KINDS.includes(librarySymbol.kind) && (
                <>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>参数</Label>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          patchLibrarySymbol({
                            parameters: [
                              ...librarySymbol.parameters,
                              { name: "", type: "", required: false },
                            ],
                          })
                        }
                      >
                        添加参数
                      </Button>
                    </div>
                    {librarySymbol.parameters.map((parameter, index) => (
                      <div
                        key={index}
                        className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]"
                      >
                        <Input
                          aria-label={`参数名 ${index + 1}`}
                          autoComplete="off"
                          value={parameter.name}
                          onChange={(event) =>
                            changeParameter(index, { name: event.target.value })
                          }
                          placeholder="名称"
                        />
                        <Input
                          aria-label={`参数类型 ${index + 1}`}
                          autoComplete="off"
                          value={parameter.type}
                          onChange={(event) =>
                            changeParameter(index, { type: event.target.value })
                          }
                          placeholder="类型"
                        />
                        <label className="flex h-8 items-center gap-1.5 text-sm">
                          <input
                            type="checkbox"
                            autoComplete="off"
                            checked={Boolean(parameter.required)}
                            onChange={(event) =>
                              changeParameter(index, {
                                required: event.target.checked,
                              })
                            }
                          />
                          必填
                        </label>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            patchLibrarySymbol({
                              parameters: librarySymbol.parameters.filter(
                                (_, i) => i !== index,
                              ),
                            })
                          }
                        >
                          移除
                        </Button>
                      </div>
                    ))}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="library-return-type">返回类型</Label>
                      <Input
                        id="library-return-type"
                        autoComplete="off"
                        value={librarySymbol.return_type ?? ""}
                        onChange={(event) =>
                          patchLibrarySymbol({
                            return_type: event.target.value,
                          })
                        }
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="library-return-description">
                        返回说明
                      </Label>
                      <Input
                        id="library-return-description"
                        autoComplete="off"
                        value={librarySymbol.return_description ?? ""}
                        onChange={(event) =>
                          patchLibrarySymbol({
                            return_description: event.target.value,
                          })
                        }
                      />
                    </div>
                  </div>
                </>
              )}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>异常或错误条件</Label>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      patchLibrarySymbol({
                        exceptions: [
                          ...librarySymbol.exceptions,
                          { type: "", description: "" },
                        ],
                      })
                    }
                  >
                    添加异常
                  </Button>
                </div>
                {librarySymbol.exceptions.map((exception, index) => (
                  <div
                    key={index}
                    className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]"
                  >
                    <Input
                      aria-label={`异常类型 ${index + 1}`}
                      autoComplete="off"
                      value={exception.type}
                      onChange={(event) =>
                        changeException(index, { type: event.target.value })
                      }
                      placeholder="异常类型"
                    />
                    <Input
                      aria-label={`异常说明 ${index + 1}`}
                      autoComplete="off"
                      value={exception.description ?? ""}
                      onChange={(event) =>
                        changeException(index, {
                          description: event.target.value,
                        })
                      }
                      placeholder="说明"
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        patchLibrarySymbol({
                          exceptions: librarySymbol.exceptions.filter(
                            (_, i) => i !== index,
                          ),
                        })
                      }
                    >
                      移除
                    </Button>
                  </div>
                ))}
              </div>
            </section>
          )}
          <section className="mt-10 flex-1 pb-24">
            <Label id="document-content-label" className="sr-only">
              正文
            </Label>
            <p id="document-content-hint" className="sr-only">
              Markdown 即时渲染。选中文本时可使用格式工具，也可直接输入 Markdown
              语法。
            </p>
            <VditorIrEditor
              className="document-vditor min-h-[26rem]"
              initialMarkdown={content}
              onChange={(markdown) => {
                setContent(markdown);
                markDirty();
              }}
              disabled={submitting}
              ariaLabelledBy="document-content-label"
              ariaDescribedBy="document-content-hint"
            />
          </section>
        </article>
      </main>
    </form>
  );
}

function MemberGroups({ symbol, onOpen }: { symbol: LibrarySymbol; onOpen: (documentId: string) => void }) {
  const labels: Partial<Record<LibrarySymbolKind, string>> = { constructor: '构造函数', field: '字段', property: '属性', method: '方法', enum_value: '枚举值', constant: '常量' }
  const groups = Object.entries(labels).map(([kind, label]) => ({ kind: kind as LibrarySymbolKind, label, members: (symbol.members ?? []).filter((member) => member.kind === kind) })).filter((group) => group.members.length > 0)
  if (!groups.length) return null
  return <div className="mt-5 space-y-4 border-t pt-5">{groups.map((group) => <div key={group.kind}><h3 className="font-medium">{group.label}</h3><div className="mt-2 divide-y rounded-md border">{group.members.map((member) => <button key={member.document_id} type="button" onClick={() => onOpen(member.document_id)} className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-muted"><span className="min-w-0 flex-1 font-mono text-sm">{member.symbol}</span><span className="min-w-0 flex-[2] truncate text-sm text-muted-foreground">{member.summary || '—'}</span></button>)}</div></div>)}</div>
}

function ApiDefinitionCard({ symbol, onOpenMember }: { symbol: LibrarySymbol; onOpenMember: (documentId: string) => void }) {
  return <section className="mt-7 rounded-xl border bg-muted/20 p-5"><div className="flex flex-wrap items-center gap-2"><span className="rounded bg-background px-2 py-1 text-xs font-medium">{symbol.language}</span><span className="rounded bg-background px-2 py-1 text-xs font-medium">{LIBRARY_SYMBOL_KINDS.find((kind) => kind.value === symbol.kind)?.label}</span>{symbol.deprecated && <span className="rounded bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive">已弃用</span>}</div><p className="mt-4 text-sm text-muted-foreground">{[symbol.package, symbol.namespace].filter(Boolean).join(' / ')}</p><h2 className="mt-2 font-mono text-base font-medium">{symbol.canonical_signature}</h2>{symbol.parameters.length > 0 && <div className="mt-5"><h3 className="font-medium">参数</h3><div className="mt-2 overflow-hidden rounded-md border"><table className="w-full text-left text-sm"><thead className="bg-muted/60 text-muted-foreground"><tr><th className="px-3 py-2 font-medium">名称</th><th className="px-3 py-2 font-medium">类型</th><th className="px-3 py-2 font-medium">说明</th></tr></thead><tbody>{symbol.parameters.map((parameter) => <tr key={parameter.name} className="border-t"><td className="px-3 py-2 font-mono">{parameter.name}</td><td className="px-3 py-2">{parameter.type}{parameter.required && <span className="ml-2 text-xs text-muted-foreground">必填</span>}</td><td className="px-3 py-2 text-muted-foreground">{parameter.description || '—'}</td></tr>)}</tbody></table></div></div>}{(symbol.return_type || symbol.return_description) && <div className="mt-5"><h3 className="font-medium">返回值</h3><div className="mt-2 overflow-hidden rounded-md border"><table className="w-full text-left text-sm"><thead className="bg-muted/60 text-muted-foreground"><tr><th className="px-3 py-2 font-medium">类型</th><th className="px-3 py-2 font-medium">说明</th></tr></thead><tbody><tr><td className="px-3 py-2 font-mono">{symbol.return_type || '—'}</td><td className="px-3 py-2 text-muted-foreground">{symbol.return_description || '—'}</td></tr></tbody></table></div></div>}{symbol.exceptions.length > 0 && <div className="mt-5"><h3 className="font-medium">异常或错误条件</h3><div className="mt-2 space-y-2">{symbol.exceptions.map((exception) => <p key={exception.type} className="text-sm"><code>{exception.type}</code>{exception.description && <span className="ml-3 text-muted-foreground">{exception.description}</span>}</p>)}</div></div>}<MemberGroups symbol={symbol} onOpen={onOpenMember} /></section>
}

function DocumentDetail({ module, document: sourceDocument, onEdit }: { module: DocumentType; document: DocumentRow; onEdit: () => void }) {
  const document = sourceDocument.library_symbol?.owner_symbol && ['constructor', 'method', 'field', 'property', 'constant'].includes(sourceDocument.library_symbol.kind)
    ? { ...sourceDocument, title: sourceDocument.library_symbol.kind === 'constructor' ? sourceDocument.library_symbol.owner_symbol.symbol : `${sourceDocument.library_symbol.owner_symbol.symbol}.${sourceDocument.library_symbol.symbol}` }
    : sourceDocument
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
  return <main className="mx-auto w-full max-w-5xl px-6 py-10 sm:px-10"><div className="mx-auto max-w-3xl"><div className="flex flex-wrap items-start justify-between gap-4 border-b pb-5"><div><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{documentLabel(module)}</span><h1 className="mt-4 text-3xl font-semibold tracking-tight">{document.title}</h1><p className="mt-2 text-sm text-muted-foreground">更新于 {new Date(document.updated_at).toLocaleString()}</p></div>{canEdit && <div className="flex gap-2"><Button variant="destructive" onClick={() => void beginDelete()}><Trash2 className="mr-2 h-4 w-4" />删除</Button><Button variant="outline" onClick={() => setVersionsOpen(true)}><History className="mr-2 h-4 w-4" />版本</Button><Button onClick={onEdit}><Pencil className="mr-2 h-4 w-4" />编辑</Button></div>}</div>
    {module === 'api' && document.library_symbol && <ApiDefinitionCard symbol={document.library_symbol} onOpenMember={(memberId) => navigate(documentUrl('api', memberId))} />}
    <section className="mt-8"><VditorMarkdownViewer markdown={document.content ?? ''} /></section><section className="mt-8 rounded-xl border p-5"><h2 className="font-medium">引用</h2><div className="mt-3 space-y-2 text-sm">{references?.items.length ? references.items.map((reference) => <p key={reference.id}>{reference.from_id === document.id ? '引用了' : '被引用于'} {reference.from_id === document.id ? reference.to_type : reference.from_type}:{(reference.from_id === document.id ? reference.to_id : reference.from_id).slice(0, 8)}</p>) : <p className="text-muted-foreground">暂无引用</p>}</div></section></div><ErrorNotification message={error} />
    <Dialog open={versionsOpen} onOpenChange={setVersionsOpen}><DialogContent><DialogHeader><DialogTitle>版本历史</DialogTitle><DialogDescription>回滚会复制历史快照并创建新版本。</DialogDescription></DialogHeader><div className="max-h-96 space-y-2 overflow-y-auto">{versions?.items.map((version) => <div key={version.id} className="flex items-center justify-between rounded border p-3 text-sm"><span>版本 {version.version_no} · {version.title}</span>{canEdit && <Button size="sm" variant="outline" onClick={() => setRollbackTarget(version.version_no)}><RotateCcw className="mr-1.5 h-3.5 w-3.5" />回滚</Button>}</div>)}</div></DialogContent></Dialog>
    <Dialog open={rollbackTarget !== null} onOpenChange={(open) => !open && setRollbackTarget(null)}><DialogContent><DialogHeader><DialogTitle>确认回滚</DialogTitle><DialogDescription>标题、正文与程序库符号定义会一同恢复，并额外创建新版本。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setRollbackTarget(null)}>取消</Button><Button onClick={() => rollbackTarget !== null && void rollback(rollbackTarget)}>确认回滚</Button></DialogFooter></DialogContent></Dialog>
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
  const ownerSymbolId = new URLSearchParams(location.search).get('owner_id')
  const librarySymbolKind = new URLSearchParams(location.search).get('kind') as LibrarySymbolKind | null
  const libraryLocation = { language: new URLSearchParams(location.search).get('language'), package: new URLSearchParams(location.search).get('package'), namespace: new URLSearchParams(location.search).get('namespace') }
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
    {documentLoading ? <p className="p-8 text-sm text-muted-foreground">加载中…</p> : mode === 'new' && canEdit ? <DocumentEditor key={`new-${module}-${containerId ?? 'root'}-${ownerSymbolId ?? 'none'}-${librarySymbolKind ?? 'default'}`} module={module} containerId={containerId} ownerSymbolId={ownerSymbolId} librarySymbolKind={librarySymbolKind} libraryLocation={libraryLocation} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(module, saved.id))} onCancel={() => requestNavigation(moduleBase(module))} /> : document && editing && canEdit ? <DocumentEditor key={document.id} module={module} document={document} containerId={document.parent_id ?? document.directory_id} onDirtyChange={setDirty} onRegisterSave={(save) => { saveRef.current = save }} onSaved={(saved) => navigate(documentUrl(module, saved.id))} onCancel={() => requestNavigation(documentUrl(module, document.id))} /> : document ? <DocumentDetail module={module} document={document} onEdit={() => navigate(`${documentUrl(module, document.id)}?mode=edit`)} /> : directory ? <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">{directory.name}</h1><p className="mt-2 text-sm text-muted-foreground">在左侧目录中选择条目，或新建文档。</p></div></main> : <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">{documentLabel(module)}</h1><p className="mt-2 text-sm text-muted-foreground">从左侧浏览文件组织，或新建文档。</p></div></main>}
    <Dialog open={pendingUrl !== null} onOpenChange={(open) => !open && setPendingUrl(null)}><DialogContent><DialogHeader><DialogTitle>未保存的更改</DialogTitle><DialogDescription>切换前请选择如何处理当前文档。</DialogDescription></DialogHeader><DialogFooter className="sm:justify-between"><Button variant="ghost" onClick={() => setPendingUrl(null)}>留在当前文档</Button><div className="flex gap-2"><Button variant="outline" onClick={() => { const target = pendingUrl; setDirty(false); setPendingUrl(null); if (target) navigate(target) }}>放弃更改并切换</Button><Button onClick={() => void saveAndNavigate()}>保存并切换</Button></div></DialogFooter></DialogContent></Dialog>
  </div>
}
