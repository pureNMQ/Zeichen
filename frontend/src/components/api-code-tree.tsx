import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Braces, ChevronDown, ChevronRight, FolderCode, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ErrorNotification } from '@/components/ui/notification'
import { api, ApiError, type LegacyCodeTreeNode, type LibrarySymbolKind } from '@/lib/api'

const SYMBOL_KIND_LABEL: Record<NonNullable<LegacyCodeTreeNode['symbol_kind']>, string> = {
  class: '类', struct: '结构体', interface: '接口', enum: '枚举', function: '函数',
  constructor: '构造函数', method: '方法', field: '字段', property: '属性', constant: '常量', enum_value: '枚举值',
}

const ROOT_KINDS: [LibrarySymbolKind, string][] = [
  ['class', '类'], ['struct', '结构体'], ['interface', '接口'], ['enum', '枚举'], ['function', '函数'],
]

function memberKinds(kind: LibrarySymbolKind | undefined): [LibrarySymbolKind, string][] {
  if (kind === 'enum') return [['enum_value', '枚举值']]
  if (kind === 'class' || kind === 'struct' || kind === 'interface') {
    return [['constructor', '构造函数'], ['field', '字段'], ['property', '属性'], ['method', '方法'], ['constant', '常量']]
  }
  return []
}

type CodeLocation = { language?: string; package?: string; namespace?: string }

function TreeItem({ node, selectedId, canEdit, onNavigate, onCreate, onDelete }: {
  node: LegacyCodeTreeNode
  selectedId?: string
  canEdit: boolean
  onNavigate: (url: string) => void
  onCreate: (kind: LibrarySymbolKind, ownerId?: string, location?: CodeLocation) => void
  onDelete: (documentId: string) => void
}) {
  const [expanded, setExpanded] = useState(true)
  const isSymbol = node.node_kind === 'symbol'
  const isNamespace = node.node_kind === 'namespace'
  const hasChildren = node.children.length > 0
  const label = isSymbol && node.symbol_kind ? SYMBOL_KIND_LABEL[node.symbol_kind] : null
  const active = isSymbol && node.document?.id === selectedId
  const members = memberKinds(node.symbol_kind)

  return <div>
    <div className={`group flex min-w-0 items-center gap-1 rounded-md pr-1 ${active ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
      {hasChildren ? <button type="button" aria-label={`${expanded ? '收起' : '展开'}${node.title}`} aria-expanded={expanded} onClick={() => setExpanded((value) => !value)} className="flex h-7 w-5 shrink-0 items-center justify-center">{expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</button> : <span className="w-5 shrink-0" />}
      {isSymbol ? <button type="button" onClick={() => node.document && onNavigate(`/documents/api/definition/${node.document.id}`)} className="min-w-0 flex-1 truncate py-1.5 text-left text-sm" title={node.document?.library_symbol?.canonical_signature ?? node.title}><span>{node.title}</span>{label && <span className={`ml-2 text-[10px] ${active ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>{label}</span>}</button> : <div className="min-w-0 flex flex-1 items-center gap-1.5 truncate py-1.5 text-sm font-medium"><span className="shrink-0">{node.node_kind === 'package' ? <FolderCode className="h-3.5 w-3.5" /> : <Braces className="h-3.5 w-3.5" />}</span><span className="truncate">{node.title}</span>{node.language && <span className="text-[10px] font-normal text-muted-foreground">{node.language}</span>}</div>}
      {isNamespace && canEdit && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{ROOT_KINDS.map(([kind, kindLabel]) => <DropdownMenuItem key={kind} onClick={() => onCreate(kind, undefined, node)}><Plus />新建{kindLabel}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>}
      {isSymbol && node.document && canEdit && <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-xs" variant="ghost" aria-label={`${node.title}更多操作`}><MoreHorizontal className="h-3.5 w-3.5" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{members.length > 0 && <><DropdownMenuLabel>新建成员</DropdownMenuLabel>{members.map(([kind, memberLabel]) => <DropdownMenuItem key={kind} onClick={() => onCreate(kind, node.id)}><Plus />新建{memberLabel}</DropdownMenuItem>)}<DropdownMenuSeparator /></>}<DropdownMenuItem onClick={() => onNavigate(`/documents/api/definition/${node.document?.id}?mode=edit`)}><Pencil />编辑</DropdownMenuItem><DropdownMenuItem variant="destructive" onClick={() => onDelete(node.document!.id)}><Trash2 />删除</DropdownMenuItem></DropdownMenuContent></DropdownMenu>}
    </div>
    {hasChildren && expanded && <div className="ml-3 border-l pl-1.5">{node.children.map((child) => <TreeItem key={child.id} node={child} selectedId={selectedId} canEdit={canEdit} onNavigate={onNavigate} onCreate={onCreate} onDelete={onDelete} />)}</div>}
  </div>
}

export function ApiCodeTreeSidebar({ projectId, projectName, selectedId, canEdit, onNavigate }: {
  projectId: string
  projectName: string
  selectedId?: string
  canEdit: boolean
  onNavigate: (url: string) => void
}) {
  const qc = useQueryClient()
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const { data, isLoading, error } = useQuery({ queryKey: ['api-code-tree', projectId], queryFn: () => api.get<{ items: LegacyCodeTreeNode[] }>(`/projects/${projectId}/libraries/code-tree`) })
  const create = (kind: LibrarySymbolKind, ownerId?: string, location?: CodeLocation) => {
    const query = new URLSearchParams({ mode: 'new', kind })
    if (ownerId) query.set('owner_id', ownerId)
    if (location?.language) query.set('language', location.language)
    if (location?.package) query.set('package', location.package)
    if (location?.namespace) query.set('namespace', location.namespace)
    onNavigate(`/documents/api?${query}`)
  }
  async function remove() {
    if (!deletingId) return
    try {
      await api.post(`/documents/api/${deletingId}/delete`)
      setDeletingId(null)
      await qc.invalidateQueries({ queryKey: ['api-code-tree', projectId] })
      onNavigate('/documents/api')
    } catch (err) { setActionError(err instanceof ApiError ? err.message : '删除失败，请重试') }
  }
  const errorMessage = actionError ?? (error instanceof ApiError ? error.message : error ? '代码树加载失败，请稍后重试' : null)
  return <><aside className="flex w-72 shrink-0 flex-col border-r bg-background" aria-label="API 代码树">
    <div className="border-b px-4 py-4"><p className="font-semibold">API</p><p className="mt-1 truncate text-xs text-muted-foreground">{projectName}</p></div>
    {canEdit && <div className="flex justify-end border-b p-3"><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" size="icon-sm" aria-label="新建"><Plus className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{ROOT_KINDS.map(([kind, label]) => <DropdownMenuItem key={kind} onClick={() => create(kind)}>新建{label}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu></div>}
    <div className="px-3 pt-3"><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">代码树</p></div>
    <div className="flex-1 overflow-y-auto p-3">{isLoading ? <p className="px-3 py-2 text-sm text-muted-foreground">加载中…</p> : error ? null : data?.items.length ? data.items.map((node) => <TreeItem key={node.id} node={node} selectedId={selectedId} canEdit={canEdit} onNavigate={onNavigate} onCreate={create} onDelete={setDeletingId} />) : <div className="px-3 py-8 text-center text-sm text-muted-foreground">暂无代码定义</div>}</div>
  </aside><ErrorNotification message={errorMessage} /><Dialog open={deletingId !== null} onOpenChange={(open) => !open && setDeletingId(null)}><DialogContent><DialogHeader><DialogTitle>确认删除</DialogTitle><DialogDescription>将删除该 API 定义；其下成员会保留为未归属的代码定义。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeletingId(null)}>取消</Button><Button variant="destructive" onClick={() => void remove()}>删除</Button></DialogFooter></DialogContent></Dialog></>
}
