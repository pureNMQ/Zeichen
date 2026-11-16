import { useRef, useState, type ChangeEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Paperclip, Trash2, Upload } from 'lucide-react'
import { api, ApiError, withProject, type AttachmentRow } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorNotification, useNotification } from '@/components/ui/notification'
import { useProjectRole } from '@/lib/current-project'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function AttachmentList({ targetType, targetId }: { targetType: string; targetId: string }) {
  const queryClient = useQueryClient()
  const role = useProjectRole()
  const { notify } = useNotification()
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['attachments', targetType, targetId],
    queryFn: () =>
      api
        .get<{ items: AttachmentRow[] }>(withProject(`/targets/${targetType}/${targetId}/attachments`))
        .then((r) => r.items),
  })

  const canEdit = role === 'editor' || role === 'owner'

  async function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    setUploading(true)
    try {
      await api.upload<AttachmentRow>(withProject(`/targets/${targetType}/${targetId}/attachments`), file)
      await queryClient.invalidateQueries({ queryKey: ['attachments', targetType, targetId] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败,请重试')
    } finally {
      setUploading(false)
    }
  }

  async function remove(id: string) {
    setError(null)
    try {
      await api.delete(`/attachments/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['attachments', targetType, targetId] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败,请重试')
    }
  }

  async function download(id: string) {
    try {
      const resp = await fetch(`/api/attachments/${id}/download`, { credentials: 'include' })
      if (!resp.ok) throw new Error('下载失败')
      const blob = await resp.blob()
      const disposition = resp.headers.get('Content-Disposition') ?? ''
      const match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
      const name = match ? decodeURIComponent(match[1]) : `attachment-${id}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      notify(err instanceof Error ? err.message : '下载失败')
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Paperclip className="h-4 w-4" />
          附件
          <span className="text-xs font-normal text-muted-foreground">
            {isLoading ? '' : `(${(data ?? []).length})`}
          </span>
        </CardTitle>
        {canEdit && (
          <>
            <input
              ref={inputRef}
              type="file"
              className="hidden"
              onChange={(e) => void onFileChange(e)}
              autoComplete="off"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={uploading}
              onClick={() => inputRef.current?.click()}
            >
              <Upload className="mr-1 h-3.5 w-3.5" />
              {uploading ? '上传中…' : '上传'}
            </Button>
          </>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        <ErrorNotification message={error} />
        {!isLoading && (data ?? []).length === 0 && (
          <p className="py-3 text-center text-sm text-muted-foreground">暂无附件</p>
        )}
        {(data ?? []).map((a) => (
          <div
            key={a.id}
            className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
          >
            <div className="flex min-w-0 items-center gap-2">
              <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="truncate">{a.file_name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{formatSize(a.size)}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => void download(a.id)} aria-label={`下载 ${a.file_name}`}>
                <Download className="h-4 w-4" />
              </Button>
              {canEdit && (
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => void remove(a.id)} aria-label={`删除 ${a.file_name}`}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
