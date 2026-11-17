import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api } from '@/lib/api'
import type { StagedProjectFile } from '@/lib/project-files'

// 创建表单的引用与附件暂存(REQ ee290fae):实体创建成功后再回填这两类关联。

export const REFERENCE_TYPE_LABELS: Record<string, string> = {
  derives: '派生',
  documents: '文档说明',
  implements: '实现',
  mentions: '提及',
}

export interface StagedReference {
  toType: 'requirement' | 'document'
  toId: string
  type: string
  label: string
}

export function CreateExtras({
  projectId,
  refs,
  onRefsChange,
  files,
  onFilesChange,
}: {
  projectId: string
  refs: StagedReference[]
  onRefsChange: (refs: StagedReference[]) => void
  files: StagedProjectFile[]
  onFilesChange: (files: StagedProjectFile[]) => void
}) {
  const [refType, setRefType] = useState('derives')
  const [targetType, setTargetType] = useState<'requirement' | 'document'>('requirement')
  const [targetId, setTargetId] = useState('')

  const { data: requirements } = useQuery({
    queryKey: ['requirements', projectId],
    queryFn: () => api.get<{ items: { id: string; title: string }[] }>(`/projects/${projectId}/requirements?limit=100`),
    enabled: targetType === 'requirement',
  })
  const { data: wikiDocs } = useQuery({
    queryKey: ['create-reference-wiki', projectId],
    queryFn: () => api.get<{ items: { id: string; title: string }[] }>(`/v2/projects/${projectId}/wiki?limit=100`),
    enabled: targetType === 'document',
  })

  const options = (targetType === 'requirement' ? requirements?.items : wikiDocs?.items) ?? []
  const selectedTitle = options.find((o) => o.id === targetId)?.title

  function addReference() {
    if (!targetId || !selectedTitle) return
    if (refs.some((r) => r.toType === targetType && r.toId === targetId && r.type === refType)) return
    onRefsChange([...refs, { toType: targetType, toId: targetId, type: refType, label: selectedTitle }])
    setTargetId('')
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>引用(可选)</Label>
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Select value={refType} onValueChange={setRefType}>
              <SelectTrigger aria-label="引用类型" className="min-w-0 flex-1 justify-between">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(REFERENCE_TYPE_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={targetType} onValueChange={(v) => { setTargetType(v as 'requirement' | 'document'); setTargetId('') }}>
              <SelectTrigger aria-label="引用目标类型" className="min-w-0 flex-1 justify-between">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="requirement">需求</SelectItem>
                <SelectItem value="document">Wiki 文档</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-1.5">
            <Select value={targetId} onValueChange={setTargetId}>
              <SelectTrigger aria-label="引用目标" className="min-w-0 flex-1 justify-between">
                <SelectValue placeholder="选择目标" />
              </SelectTrigger>
              <SelectContent>
                {options.map((o) => (
                  <SelectItem key={o.id} value={o.id}>{o.title}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button type="button" variant="outline" className="shrink-0" onClick={addReference} disabled={!targetId}>
              添加引用
            </Button>
          </div>
        </div>
        {refs.length > 0 && (
          <ul className="space-y-1" aria-label="已添加引用">
            {refs.map((r, index) => (
              <li key={`${r.toType}:${r.toId}:${r.type}`} className="flex items-center justify-between gap-2 rounded-lg border px-2 py-1 text-xs">
                <span className="truncate">
                  {REFERENCE_TYPE_LABELS[r.type]} · {r.toType === 'requirement' ? '需求' : 'Wiki 文档'}《{r.label}》
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`移除引用 ${r.label}`}
                  onClick={() => onRefsChange(refs.filter((_, i) => i !== index))}
                >
                  <X className="h-3 w-3" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="create-extras-files">附件(可选,创建后上传)</Label>
        <Input
          id="create-extras-files"
          type="file"
          multiple
          autoComplete="off"
          onChange={(e) => {
            const selected = Array.from(e.currentTarget.files ?? [], (file) => ({ file, requestId: crypto.randomUUID() }))
            e.currentTarget.value = ''
            onFilesChange([...files, ...selected])
          }}
        />
        {files.length > 0 && (
          <ul className="space-y-1" aria-label="待上传附件">
            {files.map(({ file, requestId }) => (
              <li key={requestId} className="flex items-center justify-between gap-2 rounded-lg border px-2 py-1 text-xs">
                <span className="truncate">{file.name}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`移除附件 ${file.name}`}
                  onClick={() => onFilesChange(files.filter((staged) => staged.requestId !== requestId))}
                >
                  <X className="h-3 w-3" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
