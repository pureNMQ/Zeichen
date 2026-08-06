import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Braces, ChevronDown, ChevronRight, Code2, FolderTree, KeyRound, ListTree, MoreHorizontal, Package, Pencil, Plus, RotateCcw, Settings2, SquareFunction, Trash2, Variable } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { CodeSymbolEditor } from '@/components/code-symbol-editor'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { api, ApiError, type CodeLibrary, type CodeSymbol, type CodeTreeNode } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'

function nodeIcon(node: CodeTreeNode) {
  if (node.node_kind === 'library') return <Package className="h-4 w-4" />
  if (node.node_kind === 'namespace') return <FolderTree className="h-4 w-4" />
  if (node.node_kind === 'member_group') return <ListTree className="h-4 w-4" />
  if (node.symbol_kind === 'constructor') return <KeyRound className="h-4 w-4" />
  if (node.symbol_kind === 'method') return <Settings2 className="h-4 w-4" />
  if (node.symbol_kind === 'function') return <SquareFunction className="h-4 w-4" />
  if (node.symbol_kind === 'field' || node.symbol_kind === 'property' || node.symbol_kind === 'constant') return <Variable className="h-4 w-4" />
  if (node.symbol_kind === 'class' || node.symbol_kind === 'struct' || node.symbol_kind === 'interface' || node.symbol_kind === 'enum') return <Braces className="h-4 w-4" />
  return <Code2 className="h-4 w-4" />
}

type CreateSymbolOptions = { libraryId: string; namespace?: string; ownerId?: string; kind?: CodeSymbol['kind'] }

const ROOT_SYMBOL_KINDS: Array<{ kind: CodeSymbol['kind']; label: string }> = [
  { kind: 'class', label: '类' }, { kind: 'struct', label: '结构体' }, { kind: 'interface', label: '接口' }, { kind: 'enum', label: '枚举' }, { kind: 'function', label: '函数' },
]
const CODE_SYMBOL_KINDS = new Set<CodeSymbol['kind']>(['class', 'struct', 'interface', 'enum', 'function', 'constructor', 'method', 'field', 'property', 'constant'])

function createSymbolPath(options: CreateSymbolOptions) {
  const params = new URLSearchParams()
  params.set('libraryId', options.libraryId)
  if (options.namespace !== undefined) params.set('namespace', options.namespace)
  if (options.ownerId) params.set('ownerId', options.ownerId)
  if (options.kind) params.set('kind', options.kind)
  return `/code-reference/new?${params.toString()}`
}

function memberKinds(ownerKind: CodeSymbol['kind']) {
  if (ownerKind === 'class' || ownerKind === 'struct') return [
    { kind: 'constructor' as const, label: '构造函数' }, { kind: 'method' as const, label: '方法' }, { kind: 'field' as const, label: '字段' }, { kind: 'property' as const, label: '属性' }, { kind: 'constant' as const, label: '常量' },
  ]
  if (ownerKind === 'interface') return [
    { kind: 'method' as const, label: '方法' }, { kind: 'property' as const, label: '属性' }, { kind: 'constant' as const, label: '常量' },
  ]
  return []
}

function TreeItem({ node, selectedId, canEdit, onOpen, onEdit, onDelete, onCreate, onSelectLibrary, libraryId }: { node: CodeTreeNode; selectedId?: string; canEdit: boolean; onOpen: (id: string) => void; onEdit: (id: string) => void; onDelete: (id: string) => void; onCreate: (options: CreateSymbolOptions) => void; onSelectLibrary: (id: string) => void; libraryId?: string }) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = node.children.length > 0
  const icon = nodeIcon(node)
  const currentLibraryId = node.node_kind === 'library' ? node.id : libraryId
  const availableMemberKinds = node.node_kind === 'symbol' && node.symbol_kind ? memberKinds(node.symbol_kind) : []
  const namespace = node.node_kind === 'namespace' ? (node.title === '（全局命名空间）' ? '' : node.title) : undefined
  return <div>
    <div className="group relative flex items-center gap-1 rounded px-1 hover:bg-muted">
      {hasChildren ? <button type="button" aria-label={`${expanded ? '收起' : '展开'}${node.title}`} onClick={() => setExpanded(!expanded)} className="flex h-7 w-5 items-center justify-center">{expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</button> : <span className="w-5" />}
      {node.node_kind === 'symbol' ? <button type="button" onClick={() => onOpen(node.id)} className={`flex min-w-0 flex-1 items-center gap-2 rounded py-1.5 text-left text-sm ${selectedId === node.id ? 'bg-muted' : ''}`}><span className="shrink-0 text-muted-foreground">{icon}</span><span className="block truncate">{node.title}</span></button> : <button type="button" onClick={() => node.node_kind === 'library' && onSelectLibrary(node.id)} className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left text-sm font-medium"><span>{icon}</span><span className="truncate">{node.title}</span></button>}
      {node.node_kind === 'namespace' && canEdit && currentLibraryId && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuSub><DropdownMenuSubTrigger><Plus />新建代码符号</DropdownMenuSubTrigger><DropdownMenuSubContent>{ROOT_SYMBOL_KINDS.map((item) => <DropdownMenuItem key={item.kind} onClick={() => onCreate({ libraryId: currentLibraryId, namespace, kind: item.kind })}>新建{item.label}</DropdownMenuItem>)}</DropdownMenuSubContent></DropdownMenuSub></DropdownMenuContent></DropdownMenu>}
      {node.node_kind === 'symbol' && canEdit && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{availableMemberKinds.length > 0 && <DropdownMenuSub><DropdownMenuSubTrigger><Plus />新建成员</DropdownMenuSubTrigger><DropdownMenuSubContent>{availableMemberKinds.map((item) => <DropdownMenuItem key={item.kind} onClick={() => currentLibraryId && onCreate({ libraryId: currentLibraryId, ownerId: node.id, kind: item.kind })}>新建{item.label}</DropdownMenuItem>)}</DropdownMenuSubContent></DropdownMenuSub>}<DropdownMenuItem onClick={() => onEdit(node.id)}><Pencil />编辑</DropdownMenuItem><DropdownMenuItem variant="destructive" onClick={() => onDelete(node.id)}><Trash2 />删除</DropdownMenuItem></DropdownMenuContent></DropdownMenu>}
    </div>
    {hasChildren && expanded && <div className="ml-3 border-l pl-1.5">{node.children.map((child) => <TreeItem key={child.id} node={child} selectedId={selectedId} canEdit={canEdit} onOpen={onOpen} onEdit={onEdit} onDelete={onDelete} onCreate={onCreate} onSelectLibrary={onSelectLibrary} libraryId={currentLibraryId} />)}</div>}
  </div>
}

function LibraryDialog({ projectId, open, onOpenChange, onDone }: { projectId: string; open: boolean; onOpenChange: (open: boolean) => void; onDone: () => void }) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('csharp')
  const [packageName, setPackageName] = useState('')
  const [version, setVersion] = useState('')
  const [error, setError] = useState<string | null>(null)
  async function submit() { try { await api.post(`/projects/${projectId}/code-reference/libraries`, { name, language, package: packageName, version: version || null }); onOpenChange(false); onDone() } catch (err) { setError(err instanceof ApiError ? err.message : '创建程序库失败') } }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>新建程序库</DialogTitle><DialogDescription>程序库是代码 API 参考的根节点。</DialogDescription></DialogHeader><div className="space-y-3"><div><Label htmlFor="library-name">名称</Label><Input id="library-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} /></div><div><Label htmlFor="library-language">语言</Label><Input id="library-language" autoComplete="off" value={language} onChange={(event) => setLanguage(event.target.value)} /></div><div><Label htmlFor="library-package">包或模块</Label><Input id="library-package" autoComplete="off" value={packageName} onChange={(event) => setPackageName(event.target.value)} /></div><div><Label htmlFor="library-version">版本</Label><Input id="library-version" autoComplete="off" value={version} onChange={(event) => setVersion(event.target.value)} /></div></div><DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button onClick={() => void submit()}>创建</Button></DialogFooter><ErrorNotification message={error} /></DialogContent></Dialog>
}

function TreeDeleteDialog({ symbolId, onOpenChange, onDeleted }: { symbolId: string | null; onOpenChange: (open: boolean) => void; onDeleted: () => void }) {
  const [error, setError] = useState<string | null>(null)
  async function remove() {
    if (!symbolId) return
    try { await api.post(`/code-reference/symbols/${symbolId}/delete`); onOpenChange(false); onDeleted() } catch (err) { setError(err instanceof ApiError ? err.message : '删除失败') }
  }
  return <Dialog open={symbolId !== null} onOpenChange={onOpenChange}><DialogContent><DialogHeader><DialogTitle>删除代码符号</DialogTitle><DialogDescription>类型符号删除时，其成员会一并软删除；引用会保留并标记为已删除。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button variant="destructive" onClick={() => void remove()}>删除</Button></DialogFooter><ErrorNotification message={error} /></DialogContent></Dialog>
}

function CodeSymbolDetail({ symbol, onOpenMember }: { symbol: CodeSymbol; onOpenMember: (id: string) => void }) {
  const enumMembers = symbol.kind === 'enum' ? symbol.definition.members ?? [] : []
  const memberLabels: Partial<Record<CodeSymbol['kind'], string>> = { constructor: '构造函数', field: '字段', property: '属性', method: '方法', constant: '常量' }
  const memberGroups = Object.entries(memberLabels).map(([kind, label]) => ({ kind, label, items: (symbol.members ?? []).filter((member) => member.kind === kind) })).filter((group) => group.items.length > 0)
  return <main className="mx-auto w-full max-w-5xl px-6 py-10 sm:px-10"><div className="mx-auto max-w-3xl"><div className="border-b pb-5"><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">代码 API 参考</span><h1 className="mt-4 text-3xl font-semibold tracking-tight">{symbol.name}</h1><p className="mt-2 text-sm text-muted-foreground">{symbol.qualified_name}</p></div><section className="mt-7 rounded-xl border bg-muted/20 p-5"><div className="flex flex-wrap items-center gap-2"><span className="rounded bg-background px-2 py-1 text-xs font-medium">{symbol.kind}</span><span className="rounded bg-background px-2 py-1 text-xs font-medium">{symbol.accessibility}</span>{symbol.deprecated && <span className="rounded bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive">已弃用</span>}</div><p className="mt-4 text-sm text-muted-foreground">{symbol.summary}</p><pre className="mt-4 overflow-x-auto rounded-md border bg-background p-3 text-sm">{symbol.signature}</pre>{enumMembers.length > 0 && <div className="mt-5"><h2 className="font-medium">枚举项</h2><div className="mt-2 overflow-hidden rounded-md border"><table className="w-full text-left text-sm"><thead className="bg-muted/60 text-muted-foreground"><tr><th className="px-3 py-2 font-medium">名称</th><th className="px-3 py-2 font-medium">取值</th><th className="px-3 py-2 font-medium">说明</th></tr></thead><tbody>{enumMembers.map((member) => <tr key={member.position} className="border-t"><td className="px-3 py-2 font-mono">{member.name}</td><td className="px-3 py-2 font-mono">{member.assigned_value ?? '—'}</td><td className="px-3 py-2 text-muted-foreground">{member.summary ?? '—'}</td></tr>)}</tbody></table></div></div>}{memberGroups.length > 0 && <div className="mt-5 space-y-4 border-t pt-5">{memberGroups.map((group) => <div key={group.kind}><h2 className="font-medium">{group.label}</h2><div className="mt-2 divide-y rounded-md border">{group.items.map((member) => <button key={member.id} type="button" onClick={() => onOpenMember(member.id)} className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-muted"><span className="min-w-0 flex-1 font-mono text-sm">{member.name}</span><span className="min-w-0 flex-[2] truncate text-sm text-muted-foreground">{member.summary || member.signature}</span></button>)}</div></div>)}</div>}</section><section className="mt-8"><VditorMarkdownViewer markdown={symbol.remarks ?? ''} /></section></div></main>
}

function CodeSymbolActions({ symbol, onEdit, onDeleted, onReload }: { symbol: CodeSymbol; onEdit: () => void; onDeleted: () => void; onReload: () => void }) {
  const qc = useQueryClient()
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [rollbackRevision, setRollbackRevision] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { data: versions } = useQuery({ queryKey: ['code-symbol-versions', symbol.id], queryFn: () => api.get<{ items: Array<{ revision: number; snapshot: { name: string } }> }>(`/code-reference/symbols/${symbol.id}/versions`), enabled: versionsOpen })
  async function rollback() {
    if (rollbackRevision === null) return
    try { await api.post(`/code-reference/symbols/${symbol.id}/rollback`, { revision: rollbackRevision, expected_revision: symbol.revision }); setRollbackRevision(null); setVersionsOpen(false); await qc.invalidateQueries({ queryKey: ['code-symbol', symbol.id] }); onReload() } catch (err) { setError(err instanceof ApiError ? err.message : '回滚失败') }
  }
  async function remove() {
    try { await api.post(`/code-reference/symbols/${symbol.id}/delete`); await qc.invalidateQueries({ queryKey: ['code-reference-tree'] }); setDeleteOpen(false); onDeleted() } catch (err) { setError(err instanceof ApiError ? err.message : '删除失败') }
  }
  return <><div className="absolute top-10 right-6 z-10 flex gap-2 sm:right-10"><Button variant="destructive" onClick={() => setDeleteOpen(true)}><Trash2 className="mr-2 h-4 w-4" />删除</Button><Button variant="outline" onClick={() => setVersionsOpen(true)}><RotateCcw className="mr-2 h-4 w-4" />版本</Button><Button onClick={onEdit}><Pencil className="mr-2 h-4 w-4" />编辑</Button></div><ErrorNotification message={error} /><Dialog open={versionsOpen} onOpenChange={setVersionsOpen}><DialogContent><DialogHeader><DialogTitle>版本历史</DialogTitle><DialogDescription>选择历史快照后会创建一个新的当前版本。</DialogDescription></DialogHeader><div className="max-h-96 space-y-2 overflow-y-auto">{versions?.items.map((version) => <div key={version.revision} className="flex items-center justify-between rounded border p-3 text-sm"><span>版本 {version.revision} · {version.snapshot.name}</span><Button size="sm" variant="outline" onClick={() => setRollbackRevision(version.revision)}>回滚</Button></div>)}</div></DialogContent></Dialog><Dialog open={rollbackRevision !== null} onOpenChange={(open) => !open && setRollbackRevision(null)}><DialogContent><DialogHeader><DialogTitle>确认回滚</DialogTitle><DialogDescription>符号说明和 API 定义将恢复为所选版本，并创建新的版本记录。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setRollbackRevision(null)}>取消</Button><Button onClick={() => void rollback()}>确认回滚</Button></DialogFooter></DialogContent></Dialog><Dialog open={deleteOpen} onOpenChange={setDeleteOpen}><DialogContent><DialogHeader><DialogTitle>删除代码符号</DialogTitle><DialogDescription>类型符号删除时，其成员会一并软删除；引用会保留并标记为已删除。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="destructive" onClick={() => void remove()}>删除</Button></DialogFooter></DialogContent></Dialog></>
}

export function CodeReferencePage() {
  const { id } = useParams<{ id?: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { currentProject, isLoading } = useCurrentProject()
  const role = useProjectRole()
  const [selectedLibraryId, setSelectedLibraryId] = useState<string | null>(null)
  const [libraryDialogOpen, setLibraryDialogOpen] = useState(false)
  const [treeDeleteId, setTreeDeleteId] = useState<string | null>(null)
  const canEdit = role === 'owner' || role === 'editor'
  const projectId = currentProject?.id
  const isCreating = id === 'new'
  const isEditing = new URLSearchParams(location.search).get('mode') === 'edit'
  const createParams = new URLSearchParams(location.search)
  const requestedKind = createParams.get('kind')
  const { data: libraries = [] } = useQuery({ queryKey: ['code-libraries', projectId], queryFn: () => api.get<{ items: CodeLibrary[] }>(`/projects/${projectId}/code-reference/libraries`).then((result) => result.items), enabled: Boolean(projectId) })
  const { data: tree, error: treeError } = useQuery({ queryKey: ['code-reference-tree', projectId], queryFn: () => api.get<{ items: CodeTreeNode[] }>(`/projects/${projectId}/code-reference/tree`), enabled: Boolean(projectId) })
  const { data: symbol, error: symbolError } = useQuery({ queryKey: ['code-symbol', id], queryFn: () => api.get<CodeSymbol>(`/code-reference/symbols/${id}`), enabled: Boolean(id) && !isCreating })
  const createDefaults: CreateSymbolOptions | undefined = isCreating ? {
    libraryId: createParams.get('libraryId') ?? selectedLibraryId ?? libraries[0]?.id ?? '',
    namespace: createParams.has('namespace') ? createParams.get('namespace') ?? '' : undefined,
    ownerId: createParams.get('ownerId') ?? undefined,
    kind: requestedKind && CODE_SYMBOL_KINDS.has(requestedKind as CodeSymbol['kind']) ? requestedKind as CodeSymbol['kind'] : undefined,
  } : undefined
  const error = treeError instanceof ApiError ? treeError.message : symbolError instanceof ApiError ? symbolError.message : null
  const invalidate = () => void Promise.all([qc.invalidateQueries({ queryKey: ['code-libraries', projectId] }), qc.invalidateQueries({ queryKey: ['code-reference-tree', projectId] })])
  if (isLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <p className="text-sm text-muted-foreground">请先选择项目。</p>
  return <div className="-m-6 flex min-h-[calc(100vh-0.5px)] bg-background">
    <aside className="flex w-64 shrink-0 flex-col border-r bg-background" aria-label="代码 API 参考文件组织">
      <div className="border-b px-4 py-4"><p className="font-semibold">代码 API 参考</p><p className="mt-1 truncate text-xs text-muted-foreground">{currentProject.name}</p></div>
      <div className="border-b p-3"><Input aria-label="搜索代码符号（即将支持）" autoComplete="off" placeholder="搜索代码符号（即将支持）" disabled /></div>
      {canEdit && <div className="flex justify-end border-b p-3"><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-sm" aria-label="新建"><Plus className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="w-36"><DropdownMenuItem onClick={() => setLibraryDialogOpen(true)}>新建程序库</DropdownMenuItem><DropdownMenuItem disabled={!libraries.length} onClick={() => navigate('/code-reference/new')}>新建代码符号</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>}
      <div className="flex items-center justify-between px-3 pt-3"><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">文件组织</p></div>
      <div className="flex-1 overflow-y-auto p-3">{tree?.items.length ? tree.items.map((node) => <TreeItem key={node.id} node={node} selectedId={isCreating ? undefined : id} canEdit={canEdit} onOpen={(symbolId) => navigate(`/code-reference/${symbolId}`)} onEdit={(symbolId) => navigate(`/code-reference/${symbolId}?mode=edit`)} onDelete={setTreeDeleteId} onCreate={(options) => navigate(createSymbolPath(options))} onSelectLibrary={setSelectedLibraryId} />) : <p className="px-2 py-3 text-sm text-muted-foreground">暂无内容</p>}</div>
    </aside>
    {(isCreating || (isEditing && symbol)) && canEdit ? <CodeSymbolEditor key={`${id ?? 'root'}:${location.search}`} libraries={libraries} tree={tree?.items ?? []} selectedLibraryId={selectedLibraryId} createDefaults={createDefaults} symbol={symbol} onCancel={() => navigate(isCreating ? '/code-reference' : `/code-reference/${symbol?.id}`)} onSaved={(saved) => { qc.setQueryData(['code-symbol', saved.id], saved); invalidate(); navigate(`/code-reference/${saved.id}`) }} /> : symbol ? <div className="relative min-w-0 flex-1"><CodeSymbolActions symbol={symbol} onEdit={() => navigate(`/code-reference/${symbol.id}?mode=edit`)} onDeleted={() => navigate('/code-reference')} onReload={() => void qc.invalidateQueries({ queryKey: ['code-symbol', symbol.id] })} /><CodeSymbolDetail symbol={symbol} onOpenMember={(memberId) => navigate(`/code-reference/${memberId}`)} /></div> : <main className="flex flex-1 items-center justify-center p-10"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">代码 API 参考</h1><p className="mt-2 text-sm text-muted-foreground">从左侧浏览文件组织，或新建代码符号。</p></div></main>}
    <LibraryDialog projectId={currentProject.id} open={libraryDialogOpen} onOpenChange={setLibraryDialogOpen} onDone={invalidate} />
    <TreeDeleteDialog symbolId={treeDeleteId} onOpenChange={(open) => !open && setTreeDeleteId(null)} onDeleted={() => { invalidate(); navigate('/code-reference') }} />
    <ErrorNotification message={error} />
  </div>
}
