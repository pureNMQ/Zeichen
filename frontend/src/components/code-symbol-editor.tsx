import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { VditorIrEditor } from '@/components/vditor-ir-editor'
import { api, ApiError, type CodeLibrary, type CodeSymbol, type CodeSymbolKind, type CodeTreeNode } from '@/lib/api'

const KINDS: { value: CodeSymbolKind; label: string }[] = [
  { value: 'class', label: '类' }, { value: 'struct', label: '结构体' }, { value: 'interface', label: '接口' }, { value: 'enum', label: '枚举' },
  { value: 'function', label: '函数' }, { value: 'constructor', label: '构造函数' }, { value: 'method', label: '方法' },
  { value: 'field', label: '字段' }, { value: 'property', label: '属性' }, { value: 'constant', label: '常量' },
]
const ROOT_KINDS = new Set<CodeSymbolKind>(['class', 'struct', 'interface', 'enum', 'function'])
const TYPE_KINDS = new Set<CodeSymbolKind>(['class', 'struct', 'interface'])
const CALLABLE_KINDS = new Set<CodeSymbolKind>(['function', 'constructor', 'method'])
const VALUE_KINDS = new Set<CodeSymbolKind>(['field', 'property', 'constant'])

type Parameter = { name: string; type: string; passing: 'value' | 'ref' | 'out' | 'in'; defaultValue: string; summary: string }
type Exception = { type: string; condition: string }
type EnumMember = { name: string; assignedValue: string; summary: string }
type FormDefinition = { typeParameters: string; baseType: string; interfaces: string; modifiers: string; underlyingType: string; isFlags: boolean; enumMembers: EnumMember[]; parameters: Parameter[]; returnType: string; returnSummary: string; initializer: string; exceptions: Exception[]; valueType: string; defaultValue: string; accessors: string[]; constantValue: string }

function initialDefinition(kind: CodeSymbolKind): FormDefinition {
  return { typeParameters: '', baseType: '', interfaces: '', modifiers: '', underlyingType: kind === 'enum' ? 'int' : '', isFlags: false, enumMembers: [], parameters: [], returnType: kind === 'function' || kind === 'method' ? 'void' : '', returnSummary: '', initializer: '', exceptions: [], valueType: '', defaultValue: '', accessors: ['get'], constantValue: '' }
}

function definitionFromSymbol(symbol: CodeSymbol): FormDefinition {
  const source = symbol.definition as Record<string, unknown>
  const typeParameters = Array.isArray(source.type_parameters) ? source.type_parameters.map((item) => typeof item === 'object' && item !== null && typeof (item as Record<string, unknown>).name === 'string' ? (item as Record<string, string>).name : '').filter(Boolean).join(', ') : ''
  const modifiers = Array.isArray(source.modifiers) ? source.modifiers.filter((item): item is string => typeof item === 'string').join(', ') : ''
  const interfaces = Array.isArray(source.interfaces) ? source.interfaces.filter((item): item is string => typeof item === 'string').join(', ') : ''
  const parameterRows: Parameter[] = Array.isArray(source.parameters) ? source.parameters.map((item) => { const value = item as Record<string, unknown>; return { name: typeof value.name === 'string' ? value.name : '', type: typeof value.type === 'string' ? value.type : '', passing: (value.passing === 'ref' || value.passing === 'out' || value.passing === 'in' ? value.passing : 'value') as Parameter['passing'], defaultValue: typeof value.default_value === 'string' ? value.default_value : '', summary: typeof value.summary === 'string' ? value.summary : '' } }) : []
  const exceptionRows = Array.isArray(source.exceptions) ? source.exceptions.map((item) => { const value = item as Record<string, unknown>; return { type: typeof value.type === 'string' ? value.type : '', condition: typeof value.condition === 'string' ? value.condition : '' } }) : []
  const returns = source.returns as Record<string, unknown> | undefined
  return { ...initialDefinition(symbol.kind), typeParameters, interfaces, modifiers, baseType: typeof source.base_type === 'string' ? source.base_type : '', underlyingType: typeof source.underlying_type === 'string' ? source.underlying_type : '', isFlags: source.is_flags === true, enumMembers: Array.isArray(source.members) ? source.members.map((item) => { const value = item as Record<string, unknown>; return { name: typeof value.name === 'string' ? value.name : '', assignedValue: typeof value.assigned_value === 'string' ? value.assigned_value : '', summary: typeof value.summary === 'string' ? value.summary : '' } }) : [], parameters: parameterRows, returnType: typeof returns?.type === 'string' ? returns.type : '', returnSummary: typeof returns?.summary === 'string' ? returns.summary : '', initializer: typeof source.initializer === 'string' ? source.initializer : '', exceptions: exceptionRows, valueType: typeof source.value_type === 'string' ? source.value_type : '', defaultValue: typeof source.default_value === 'string' ? source.default_value : '', accessors: Array.isArray(source.accessors) ? source.accessors.filter((item): item is string => typeof item === 'string') : ['get'], constantValue: typeof source.value === 'string' ? source.value : '' }
}

function splitList(value: string) { return value.split(',').map((item) => item.trim()).filter(Boolean) }

function definitionPayload(kind: CodeSymbolKind, definition: FormDefinition) {
  const modifiers = splitList(definition.modifiers)
  const typeParameters = splitList(definition.typeParameters).map((name) => ({ name, constraints: [] }))
  if (TYPE_KINDS.has(kind)) return { type_parameters: typeParameters, base_type: definition.baseType.trim() || null, interfaces: splitList(definition.interfaces), modifiers }
  if (kind === 'enum') return { underlying_type: definition.underlyingType.trim() || null, is_flags: definition.isFlags, members: definition.enumMembers.map((member, position) => ({ position, name: member.name, assigned_value: member.assignedValue.trim() || null, summary: member.summary.trim() || null })) }
  if (CALLABLE_KINDS.has(kind)) {
    const common = { parameters: definition.parameters.map((parameter) => ({ name: parameter.name, type: parameter.type, passing: parameter.passing, default_value: parameter.defaultValue.trim() || null, summary: parameter.summary.trim() || null })), exceptions: definition.exceptions.map((exception) => ({ type: exception.type, condition: exception.condition })), type_parameters: typeParameters, modifiers }
    return kind === 'constructor' ? { ...common, initializer: definition.initializer.trim() || null } : { ...common, returns: { type: definition.returnType, summary: definition.returnSummary.trim() || null } }
  }
  if (kind === 'field') return { value_type: definition.valueType, default_value: definition.defaultValue.trim() || null, modifiers }
  if (kind === 'property') return { value_type: definition.valueType, accessors: definition.accessors, modifiers }
  return { value_type: definition.valueType, value: definition.constantValue }
}

function flattenSymbols(nodes: CodeTreeNode[]) {
  const results: Array<CodeTreeNode & { libraryId: string }> = []
  const visit = (items: CodeTreeNode[], libraryId: string | null) => items.forEach((item) => {
    const nextLibraryId = item.node_kind === 'library' ? item.id : libraryId
    if (item.node_kind === 'symbol' && nextLibraryId) results.push({ ...item, libraryId: nextLibraryId })
    visit(item.children, nextLibraryId)
  })
  visit(nodes, null)
  return results
}

function ownerKinds(kind: CodeSymbolKind): CodeSymbolKind[] {
  if (kind === 'constructor' || kind === 'field') return ['class', 'struct']
  if (kind === 'method' || kind === 'property' || kind === 'constant') return ['class', 'struct', 'interface']
  return []
}

function TextField({ id, label, value, onChange, placeholder, disabled = false }: { id: string; label: string; value: string; onChange: (value: string) => void; placeholder?: string; disabled?: boolean }) {
  return <div className="space-y-1.5"><Label htmlFor={id}>{label}</Label><Input id={id} autoComplete="off" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} disabled={disabled} /></div>
}

function Repeater({ label, addLabel, onAdd, children }: { label: string; addLabel: string; onAdd: () => void; children: React.ReactNode }) {
  return <section className="space-y-2"><div className="flex items-center justify-between"><Label>{label}</Label><Button type="button" size="sm" variant="outline" onClick={onAdd}><Plus className="mr-1 h-3.5 w-3.5" />{addLabel}</Button></div>{children}</section>
}

function DefinitionForm({ kind, definition, onPatch }: { kind: CodeSymbolKind; definition: FormDefinition; onPatch: (patch: Partial<FormDefinition>) => void }) {
  const patchParameter = (index: number, patch: Partial<Parameter>) => onPatch({ parameters: definition.parameters.map((item, i) => i === index ? { ...item, ...patch } : item) })
  const patchException = (index: number, patch: Partial<Exception>) => onPatch({ exceptions: definition.exceptions.map((item, i) => i === index ? { ...item, ...patch } : item) })
  const patchEnumMember = (index: number, patch: Partial<EnumMember>) => onPatch({ enumMembers: definition.enumMembers.map((item, i) => i === index ? { ...item, ...patch } : item) })
  return <section className="mt-6 space-y-5 rounded-xl border bg-muted/20 p-4 sm:p-5"><h2 className="font-medium">{KINDS.find((item) => item.value === kind)?.label}定义</h2>{TYPE_KINDS.has(kind) && <div className="grid gap-3 sm:grid-cols-2"><TextField id="type-parameters" label="泛型参数（逗号分隔）" value={definition.typeParameters} onChange={(typeParameters) => onPatch({ typeParameters })} /><TextField id="base-type" label="基类" value={definition.baseType} onChange={(baseType) => onPatch({ baseType })} disabled={kind === 'interface'} /><div className="sm:col-span-2"><TextField id="interfaces" label="实现或继承的接口（逗号分隔）" value={definition.interfaces} onChange={(interfaces) => onPatch({ interfaces })} /></div></div>}{kind !== 'constant' && <TextField id="modifiers" label="修饰符（逗号分隔）" value={definition.modifiers} onChange={(modifiers) => onPatch({ modifiers })} placeholder="例如：abstract, sealed" />}{kind === 'enum' && <><TextField id="underlying-type" label="底层类型" value={definition.underlyingType} onChange={(underlyingType) => onPatch({ underlyingType })} /><label className="flex items-center gap-2 text-sm"><input type="checkbox" autoComplete="off" checked={definition.isFlags} onChange={(event) => onPatch({ isFlags: event.target.checked })} />位标志枚举</label><Repeater label="枚举项" addLabel="添加枚举项" onAdd={() => onPatch({ enumMembers: [...definition.enumMembers, { name: '', assignedValue: '', summary: '' }] })}>{definition.enumMembers.map((member, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_1.5fr_auto]"><Input aria-label={`枚举项名称 ${index + 1}`} autoComplete="off" placeholder="名称" value={member.name} onChange={(event) => patchEnumMember(index, { name: event.target.value })} /><Input aria-label={`枚举项取值 ${index + 1}`} autoComplete="off" placeholder="取值（可选）" value={member.assignedValue} onChange={(event) => patchEnumMember(index, { assignedValue: event.target.value })} /><Input aria-label={`枚举项说明 ${index + 1}`} autoComplete="off" placeholder="说明（可选）" value={member.summary} onChange={(event) => patchEnumMember(index, { summary: event.target.value })} /><Button type="button" size="sm" variant="ghost" onClick={() => onPatch({ enumMembers: definition.enumMembers.filter((_, i) => i !== index) })}>移除</Button></div>)}</Repeater></>}{CALLABLE_KINDS.has(kind) && <><Repeater label="参数" addLabel="添加参数" onAdd={() => onPatch({ parameters: [...definition.parameters, { name: '', type: '', passing: 'value', defaultValue: '', summary: '' }] })}>{definition.parameters.map((parameter, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto]"><Input aria-label={`参数名称 ${index + 1}`} autoComplete="off" placeholder="名称" value={parameter.name} onChange={(event) => patchParameter(index, { name: event.target.value })} /><Input aria-label={`参数类型 ${index + 1}`} autoComplete="off" placeholder="类型" value={parameter.type} onChange={(event) => patchParameter(index, { type: event.target.value })} /><select aria-label={`参数传递方式 ${index + 1}`} value={parameter.passing} onChange={(event) => patchParameter(index, { passing: event.target.value as Parameter['passing'] })} className="h-9 rounded-md border bg-background px-2 text-sm"><option value="value">值</option><option value="ref">ref</option><option value="out">out</option><option value="in">in</option></select><Button type="button" size="sm" variant="ghost" onClick={() => onPatch({ parameters: definition.parameters.filter((_, i) => i !== index) })}>移除</Button><Input className="sm:col-span-2" aria-label={`参数默认值 ${index + 1}`} autoComplete="off" placeholder="默认值（可选）" value={parameter.defaultValue} onChange={(event) => patchParameter(index, { defaultValue: event.target.value })} /><Input className="sm:col-span-2" aria-label={`参数说明 ${index + 1}`} autoComplete="off" placeholder="说明（可选）" value={parameter.summary} onChange={(event) => patchParameter(index, { summary: event.target.value })} /></div>)}</Repeater>{kind === 'constructor' ? <TextField id="initializer" label="构造函数初始化器" value={definition.initializer} onChange={(initializer) => onPatch({ initializer })} placeholder="例如：base(name)" /> : <div className="grid gap-3 sm:grid-cols-2"><TextField id="return-type" label="返回类型" value={definition.returnType} onChange={(returnType) => onPatch({ returnType })} /><TextField id="return-summary" label="返回说明" value={definition.returnSummary} onChange={(returnSummary) => onPatch({ returnSummary })} /></div>}<Repeater label="异常或错误条件" addLabel="添加异常" onAdd={() => onPatch({ exceptions: [...definition.exceptions, { type: '', condition: '' }] })}>{definition.exceptions.map((exception, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]"><Input aria-label={`异常类型 ${index + 1}`} autoComplete="off" placeholder="异常类型" value={exception.type} onChange={(event) => patchException(index, { type: event.target.value })} /><Input aria-label={`异常条件 ${index + 1}`} autoComplete="off" placeholder="触发条件" value={exception.condition} onChange={(event) => patchException(index, { condition: event.target.value })} /><Button type="button" size="sm" variant="ghost" onClick={() => onPatch({ exceptions: definition.exceptions.filter((_, i) => i !== index) })}>移除</Button></div>)}</Repeater></>}{VALUE_KINDS.has(kind) && <><TextField id="value-type" label="值类型" value={definition.valueType} onChange={(valueType) => onPatch({ valueType })} />{kind === 'field' && <TextField id="default-value" label="默认值" value={definition.defaultValue} onChange={(defaultValue) => onPatch({ defaultValue })} />}{kind === 'property' && <fieldset><legend className="text-sm font-medium">访问器</legend><div className="mt-2 flex gap-4">{['get', 'set', 'init'].map((accessor) => <label key={accessor} className="flex items-center gap-1.5 text-sm"><input type="checkbox" autoComplete="off" checked={definition.accessors.includes(accessor)} onChange={(event) => onPatch({ accessors: event.target.checked ? [...definition.accessors, accessor] : definition.accessors.filter((item) => item !== accessor) })} />{accessor}</label>)}</div></fieldset>}{kind === 'constant' && <TextField id="constant-value" label="常量值" value={definition.constantValue} onChange={(constantValue) => onPatch({ constantValue })} />}</>}</section>
}

export function CodeSymbolEditor({ libraries, tree, selectedLibraryId, createDefaults, symbol, onCancel, onSaved }: { libraries: CodeLibrary[]; tree: CodeTreeNode[]; selectedLibraryId: string | null; createDefaults?: { libraryId?: string; namespace?: string; ownerId?: string; kind?: CodeSymbolKind }; symbol?: CodeSymbol; onCancel: () => void; onSaved: (symbol: CodeSymbol) => void }) {
  const [libraryId, setLibraryId] = useState(symbol?.library_id ?? createDefaults?.libraryId ?? selectedLibraryId ?? libraries[0]?.id ?? '')
  const [ownerId, setOwnerId] = useState(symbol?.owner_symbol_id ?? createDefaults?.ownerId ?? '')
  const [namespace, setNamespace] = useState(symbol?.namespace ?? createDefaults?.namespace ?? '')
  const [kind, setKind] = useState<CodeSymbolKind>(symbol?.kind ?? createDefaults?.kind ?? 'class')
  const [name, setName] = useState(symbol?.name ?? '')
  const [summary, setSummary] = useState(symbol?.summary ?? '')
  const [remarks, setRemarks] = useState(symbol?.remarks ?? '')
  const [accessibility, setAccessibility] = useState<CodeSymbol['accessibility']>(symbol?.accessibility ?? 'public')
  const [sourceDeclaration, setSourceDeclaration] = useState(symbol?.source_declaration ?? '')
  const [sinceVersion, setSinceVersion] = useState(symbol?.since_version ?? '')
  const [deprecated, setDeprecated] = useState(symbol?.deprecated ?? false)
  const [definition, setDefinition] = useState<FormDefinition>(() => symbol ? definitionFromSymbol(symbol) : initialDefinition(createDefaults?.kind ?? 'class'))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const symbols = useMemo(() => flattenSymbols(tree), [tree])
  const isRoot = ROOT_KINDS.has(kind)
  const owners = symbols.filter((symbol) => symbol.libraryId === libraryId && ownerKinds(kind).includes(symbol.symbol_kind as CodeSymbolKind))

  function changeKind(nextKind: CodeSymbolKind) { setKind(nextKind); setOwnerId(''); setDefinition(initialDefinition(nextKind)) }
  async function submit() {
    setError(null)
    setSubmitting(true)
    try {
      const payload = { name, summary, remarks, accessibility, source_declaration: sourceDeclaration || null, since_version: sinceVersion || null, deprecated, definition: definitionPayload(kind, definition) }
      const saved = symbol
        ? await api.patch<CodeSymbol>(`/code-reference/symbols/${symbol.id}`, { expected_revision: symbol.revision, ...payload })
        : await api.post<CodeSymbol>(`/code-reference/libraries/${libraryId}/symbols`, { kind, ...payload, ...(isRoot ? { namespace } : { owner_symbol_id: ownerId }) })
      onSaved(saved)
    } catch (err) { setError(err instanceof ApiError ? err.message : '创建代码符号失败') } finally { setSubmitting(false) }
  }
  return <form onSubmit={(event) => { event.preventDefault(); void submit() }} className="flex min-w-0 flex-1 flex-col"><ErrorNotification message={error} /><header className="border-b bg-background"><div className="mx-auto flex min-h-14 w-full max-w-5xl items-center justify-between gap-3 px-5 sm:px-8"><div><span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">代码 API 参考</span><span className="ml-3 text-xs text-muted-foreground">{symbol ? '编辑代码符号' : '新建代码符号'}</span></div><div className="flex gap-2"><Button type="button" size="sm" variant="outline" onClick={onCancel}>取消</Button><Button type="submit" size="sm" disabled={submitting}>{submitting ? '保存中…' : symbol ? '保存' : '创建'}</Button></div></div></header><main className="flex-1 bg-muted/30"><article className="mx-auto w-full max-w-3xl px-6 py-8 sm:px-10 sm:py-10"><Label htmlFor="symbol-name" className="sr-only">名称</Label><Input id="symbol-name" autoComplete="off" value={name} onChange={(event) => setName(event.target.value)} placeholder="未命名代码符号" className="h-auto rounded-none border-0 bg-transparent px-0 py-0 text-[2.5rem] font-semibold leading-tight tracking-[-0.045em] shadow-none placeholder:text-muted-foreground/55 focus-visible:ring-0 md:!text-5xl" /><section className="mt-6 space-y-4 rounded-xl border bg-background p-4 sm:p-5"><h2 className="font-medium">API 定义</h2><div className="grid gap-3 sm:grid-cols-2"><div className="space-y-1.5"><Label htmlFor="symbol-library">程序库</Label><select id="symbol-library" aria-label="程序库" value={libraryId} disabled={Boolean(symbol)} onChange={(event) => { setLibraryId(event.target.value); setOwnerId('') }} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{libraries.map((library) => <option key={library.id} value={library.id}>{library.name}</option>)}</select></div><div className="space-y-1.5"><Label htmlFor="symbol-kind">种类</Label><select id="symbol-kind" aria-label="种类" value={kind} disabled={Boolean(symbol)} onChange={(event) => changeKind(event.target.value as CodeSymbolKind)} className="h-9 w-full rounded-md border bg-background px-2 text-sm">{KINDS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div></div><div className="grid gap-3 sm:grid-cols-2"><div className="space-y-1.5"><Label htmlFor="symbol-accessibility">可见性</Label><select id="symbol-accessibility" aria-label="可见性" value={accessibility} onChange={(event) => setAccessibility(event.target.value as CodeSymbol['accessibility'])} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="public">public</option><option value="protected">protected</option><option value="internal">internal</option><option value="private">private</option></select></div><TextField id="symbol-since" label="引入版本" value={sinceVersion} onChange={setSinceVersion} /></div>{isRoot ? <TextField id="symbol-namespace" label="命名空间" value={namespace} onChange={setNamespace} disabled={Boolean(symbol)} /> : <div className="space-y-1.5"><Label htmlFor="symbol-owner">所属类型</Label><select id="symbol-owner" aria-label="所属类型" value={ownerId} disabled={Boolean(symbol)} onChange={(event) => setOwnerId(event.target.value)} className="h-9 w-full rounded-md border bg-background px-2 text-sm"><option value="">选择所属类型</option>{owners.map((owner) => <option key={owner.id} value={owner.id}>{owner.title}</option>)}</select><p className="text-xs text-muted-foreground">成员将继承所属类型的命名空间。</p></div>}<TextField id="symbol-summary" label="摘要" value={summary} onChange={setSummary} /><TextField id="symbol-source" label="源码声明" value={sourceDeclaration} onChange={setSourceDeclaration} /><label className="flex items-center gap-2 text-sm"><input type="checkbox" autoComplete="off" checked={deprecated} onChange={(event) => setDeprecated(event.target.checked)} />已弃用</label><DefinitionForm kind={kind} definition={definition} onPatch={(patch) => setDefinition((current) => ({ ...current, ...patch }))} /></section><section className="mt-10 pb-24"><Label id="symbol-remarks-label" className="sr-only">完整说明</Label><p id="symbol-remarks-hint" className="mb-3 text-sm text-muted-foreground">完整说明使用 Markdown 编辑器；摘要独立用于列表、树和搜索结果。</p><VditorIrEditor className="document-vditor min-h-[26rem]" initialMarkdown={remarks} onChange={setRemarks} disabled={submitting} ariaLabelledBy="symbol-remarks-label" ariaDescribedBy="symbol-remarks-hint" /></section></article></main></form>
}
