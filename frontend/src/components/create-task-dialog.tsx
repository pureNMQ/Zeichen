import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api, ApiError, type RequirementRow } from '@/lib/api'
import { clearDraft, readDraft, writeDraft } from '@/lib/form-draft'
import { CreateExtras, type StagedReference } from '@/components/create-extras'
import { useCurrentProject } from '@/lib/current-project'

export function CreateTaskDialog({
  open,
  onOpenChange,
  presetRequirementId = null,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  presetRequirementId?: string | null
  onCreated?: () => void
}) {
  const { projectId } = useCurrentProject()
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [requirementId, setRequirementId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [refs, setRefs] = useState<StagedReference[]>([])
  const [files, setFiles] = useState<File[]>([])

  const draftKey = projectId ? `zeichen.draft.task:${projectId}` : null

  useEffect(() => {
    if (open) {
      setError(null)
      if (draftKey) {
        const draft = readDraft<{ title: string; description: string; requirementId: string | null }>(draftKey)
        if (draft) {
          setTitle(draft.title ?? '')
          setDescription(draft.description ?? '')
          // 从需求详情派生创建时,预设需求优先于草稿
          setRequirementId(presetRequirementId ?? draft.requirementId ?? null)
          return
        }
      }
      setTitle('')
      setDescription('')
      setRequirementId(presetRequirementId)
      setRefs([])
      setFiles([])
    }
  }, [open, presetRequirementId, draftKey])

  useEffect(() => {
    if (!open || !draftKey) return
    // 全空内容不持久化,并清掉既有草稿(手动清空后重开即为空白表单)
    if (!title && !description && !requirementId) {
      clearDraft(draftKey)
      return
    }
    writeDraft(draftKey, { title, description, requirementId })
  }, [open, draftKey, title, description, requirementId])

  function clearFormDraft() {
    if (draftKey) clearDraft(draftKey)
    setTitle('')
    setDescription('')
    setRequirementId(presetRequirementId)
    setRefs([])
    setFiles([])
    setError(null)
  }

  const { data: requirements } = useQuery({
    queryKey: ['requirements', projectId],
    queryFn: () =>
      api.get<{ items: RequirementRow[]; next_cursor: string | null }>(
        `/projects/${projectId}/requirements?limit=100`,
      ),
    enabled: open && !!projectId,
  })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!projectId) return
    setError(null)
    setSubmitting(true)
    try {
      const created = await api.post<{ id: string }>(`/projects/${projectId}/tasks`, {
        title: title.trim(),
        description: description.trim() || null,
        requirement_id: requirementId,
      })
      // 依次回填暂存的引用与附件;失败保留剩余项,提示后可重试
      const remainingRefs = [...refs]
      const remainingFiles = [...files]
      try {
        while (remainingRefs.length > 0) {
          const r = remainingRefs[0]
          await api.post(`/targets/task/${created.id}/references`, { from_type: 'task', from_id: created.id, to_type: r.toType, to_id: r.toId, type: r.type })
          remainingRefs.shift()
        }
        while (remainingFiles.length > 0) {
          await api.upload(`/targets/task/${created.id}/attachments`, remainingFiles[0])
          remainingFiles.shift()
        }
      } catch {
        setRefs(remainingRefs)
        setFiles(remainingFiles)
        setError('已创建,但部分引用/附件回填失败,可稍后在详情页重试')
        return
      }
      setRefs([])
      setFiles([])
      if (draftKey) clearDraft(draftKey)
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
      onCreated?.()
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
          <DialogTitle>新建任务</DialogTitle>
          <DialogDescription>任务可挂到需求下(承接拆解),也可作为独立任务。</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="task-title">标题</Label>
            <Input id="task-title" value={title} onChange={(e) => setTitle(e.target.value)} autoComplete="off" maxLength={256} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="task-desc">描述</Label>
            <Input id="task-desc" value={description} onChange={(e) => setDescription(e.target.value)} autoComplete="off" maxLength={512} />
          </div>
          <div className="space-y-1.5">
            <Label>关联需求</Label>
            <Select value={requirementId ?? 'none'} onValueChange={(v) => setRequirementId(v === 'none' ? null : v)}>
              <SelectTrigger size="sm" aria-label="关联需求" className="w-full justify-between">
                <SelectValue placeholder="独立任务(不关联)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">独立任务(不关联)</SelectItem>
                {(requirements?.items ?? []).filter((r) => r.status !== 'pending').map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {projectId && <CreateExtras projectId={projectId} refs={refs} onRefsChange={setRefs} files={files} onFilesChange={setFiles} />}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={clearFormDraft}>
              清空草稿
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
