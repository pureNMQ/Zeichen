import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { MarkdownComposer } from '@/components/markdown-composer'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { api, ApiError, type RequirementRow, type TaskRow } from '@/lib/api'
import { useProjectRole } from '@/lib/current-project'
import { useCurrentPage } from '@/lib/use-current-page'
import { useAuth } from '@/lib/auth'
import { clearDraft, readDraft, writeDraft } from '@/lib/form-draft'
import { useProjectCompletion } from '@/lib/project-completion'
import { associateProjectFile, projectFileUpload, type FileTargetKind } from '@/lib/project-files'

type WorkItem = RequirementRow | TaskRow
type Draft = { title: string; description: string; version?: number }
type SaveReceipt = {
  id: string | null
  requestId: string
  title: string
  description: string
  // Older drafts may still have uploads awaiting association.
  attachments?: { id: string; name: string }[]
}
type EditorProps = { kind: FileTargetKind; creating?: boolean }

export function WorkEditorPage({ kind, creating = false }: EditorProps) {
  const { projectId = '', id = '', taskId = '' } = useParams()
  const role = useProjectRole()
  const code = kind === 'tasks' ? taskId : id
  const { data: item, error } = useQuery({
    queryKey: ['work-editor-source', projectId, kind, code, id, creating],
    queryFn: async () => {
      const resource = creating ? 'requirements' : kind
      const target = creating ? id : code
      const row = await api.get<WorkItem>(resource === 'tasks' ? `/tasks/${target}?project_id=${projectId}` : `/projects/${projectId}/${resource}/${target}`)
      if (row.project_id !== projectId || row.id !== target
        || (resource === 'tasks' && (!('requirement_id' in row) || row.requirement_id !== id))) {
        throw new Error('该工作项不属于当前需求或项目。')
      }
      return row
    },
    enabled: !!projectId && (!creating || kind === 'tasks'), retry: false,
  })
  if (error) return <ErrorNotification message={error.message} />
  if ((!creating || kind === 'tasks') && !item) return <p role="status">加载中…</p>
  if (role !== 'owner' && role !== 'editor') return <ErrorNotification message="当前角色无编辑权限。" />
  return <WorkForm key={[projectId, id, kind, code, creating].join(':')} projectId={projectId} parent={id}
    kind={kind} item={creating ? undefined : item} />
}

function WorkForm({ projectId, parent, kind, item }: {
  projectId: string; parent: string; kind: FileTargetKind; item?: WorkItem
}) {
  const { user } = useAuth()
  const draftKey = ['zeichen.work-draft', user?.id, projectId, parent, kind, item?.id || 'new'].join(':')
  const [draft, setDraft] = useState<Draft>(() => readDraft<Draft>(draftKey) ?? {
    title: item?.title ?? '', description: item?.description ?? '', version: item?.version,
  })
  const receiptKey = draftKey + ':receipt'
  const [receipt, setReceipt] = useState<SaveReceipt | null>(() => readDraft<SaveReceipt>(receiptKey))
  const saving = useRef(false)
  const isCurrentPage = useCurrentPage()
  function remember(value: SaveReceipt) {
    writeDraft(receiptKey, value)
    setReceipt(value)
  }
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const qc = useQueryClient()
  const lookup = useProjectCompletion(projectId)
  const base = `/projects/${projectId}`
  const collection = `${base}/requirements`
  const parentHref = parent ? `${collection}/${parent}` : collection
  const cancelHref = kind === 'tasks' ? parentHref + (item ? `?task=${item.id}` : '?tab=tasks') : item ? parentHref + '?tab=body' : parentHref
  const noun = kind === 'tasks' ? '任务' : '需求'
  useEffect(() => {
    if (receipt) return
    if (draft.title !== (item?.title ?? '') || draft.description !== (item?.description ?? '')) writeDraft(draftKey, draft)
    else clearDraft(draftKey)
  }, [draft, draftKey, item?.title, item?.description, receipt])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (saving.current || uploading || (!receipt && !draft.title.trim())) return
    saving.current = true
    setError(''); setBusy(true)
    let pending = receipt
    try {
      if (!pending) {
        pending = { title: draft.title.trim(), description: draft.description,
          requestId: crypto.randomUUID(), id: null }
        // Capture the original POST body before sending. A lost response may already have created the item.
        if (!item) remember(pending)
      }
      if (!pending.id) {
        const fields = { title: pending.title, description: pending.description }
        const saved = item
          ? await api.patch<WorkItem>(`/${kind}/${item.id}?project_id=${projectId}`, { ...fields, expected_version: draft.version })
          : await api.post<WorkItem>(`${base}/${kind}`, { ...fields, request_id: pending.requestId,
            ...(kind === 'tasks' ? { requirement_id: parent } : {}) })
        if (!saved?.id || (saved.project_id && saved.project_id !== projectId)) throw new Error('保存回执无效，请重试。')
        pending = { ...pending, id: saved.id }
        if (pending.attachments?.length) remember(pending)
      }
      const targetId = pending.id!
      for (const attachment of pending.attachments ?? []) {
        // PUT is idempotent if the previous response was lost after the file was associated.
        await associateProjectFile(projectId, kind, targetId, attachment.id)
        pending = { ...pending, attachments: pending.attachments?.filter(f => f.id !== attachment.id) }
        remember(pending)
      }
      clearDraft(draftKey)
      clearDraft(receiptKey)
      await Promise.all(['work-editor-source', 'task', 'requirement', 'requirements', 'requirement-tasks',
        'requirement-timeline', 'work-versions', 'project-files', 'project-file-usage'].map(
        key => qc.invalidateQueries({ queryKey: [key] }),
      ))
      const next = kind === 'requirements' ? `${collection}/${targetId}?tab=body`
        : item ? `${parentHref}?task=${targetId}` : `${parentHref}?tab=tasks&focus=${targetId}`
      if (isCurrentPage()) navigate(next, { replace: true })
    } catch (err) {
      if (!pending?.id && err instanceof ApiError && [400,403,404,409,413,422].includes(err.status)) {
        clearDraft(receiptKey); setReceipt(null)
        if (item && err.status === 409) void qc.invalidateQueries({ queryKey:['work-editor-source'] })
      }
      setError(pending?.id && pending.attachments?.length ? '正文已保存。附件尚未全部关联，请重试。' : item && err instanceof ApiError && err.status === 409
        ? '内容已被修改。草稿已保留，请对照最新版本后重试。' : err instanceof Error ? err.message : '保存失败，请重试。')
    } finally { saving.current = false; setBusy(false) }
  }
  if (receipt) return <form onSubmit={save} className="mx-auto max-w-4xl space-y-4">
    <h1 className="break-words text-xl font-semibold">{receipt.title}</h1>
    <p role="status" className="text-sm text-muted-foreground">{receipt.id
      ? `${receipt.id} 正文已保存${receipt.attachments?.length ? '，以下附件待关联。' : '。'}`
      : '正在确认创建结果。离开后可从此编辑页继续。'}</p>
    <ErrorNotification message={error} />
    {receipt.attachments?.map(f => <div key={f.id} className="flex items-center gap-2 text-sm"><span>{f.name}</span>
      {receipt.id && <Button type="button" size="sm" variant="ghost" disabled={busy}
        onClick={() => remember({ ...receipt, attachments:receipt.attachments?.filter(x => x.id !== f.id) })}>移除</Button>}</div>)}
    <div className="flex gap-2"><Button type="button" variant="outline" onClick={() => navigate(cancelHref)}>返回</Button>
      <Button type="submit" disabled={busy}>{busy ? '保存中…' : receipt.id ? '继续保存' : '确认创建结果'}</Button></div>
  </form>
  return <form onSubmit={save} className="mx-auto max-w-4xl space-y-5">
    <Link className="text-sm text-muted-foreground hover:underline" to={cancelHref}>{parent || '需求看板'}</Link>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-semibold">{item ? '编辑' : '新建'}{noun}</h1>
      <div className="flex gap-2"><Button type="button" variant="outline" disabled={busy} onClick={() => navigate(cancelHref)}>返回</Button>
        <Button type="submit" disabled={busy || uploading || !draft.title.trim()}>{busy ? '保存中…' : '保存'}</Button></div>
    </div>
    <ErrorNotification message={error} />
    {item && item.version !== draft.version && <div className="flex flex-wrap items-center gap-2 text-sm">
      <a href={cancelHref} target="_blank" rel="noreferrer" className="underline">查看当前版本</a>
      <Button type="button" variant="outline" size="sm" onClick={() => setDraft({ ...draft, version: item.version })}>已核对，基于当前版本继续</Button>
    </div>}
    <div className="space-y-2"><Label htmlFor="work-title">标题</Label>
      <Input id="work-title" autoComplete="off" maxLength={256} disabled={busy} required value={draft.title}
        onChange={e => setDraft({ ...draft, title: e.target.value })} /></div>
    <MarkdownComposer className="[--writing-height:16rem]" label="正文" id="work-body" value={draft.description} lookup={lookup}
      disabled={busy} onChange={description => setDraft({ ...draft, description })}
      upload={projectFileUpload(projectId)} onUploadPending={setUploading} />
  </form>
}
