import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError, type CommentRow } from '@/lib/api'
import { ErrorNotification } from '@/components/ui/notification'

export function CommentStream({ targetType, targetId, canEdit }: { targetType: string; targetId: string; canEdit: boolean }) {
  const qc = useQueryClient()
  const key = ['comments', targetType, targetId]
  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => api.get<{ items: CommentRow[] }>(`/targets/${targetType}/${targetId}/comments?limit=50`),
  })
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api.post(`/targets/${targetType}/${targetId}/comments`, { body: body.trim() })
      setBody('')
      await qc.invalidateQueries({ queryKey: key })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '评论失败')
    }
  }

  async function remove(id: string) {
    try {
      await api.delete(`/comments/${id}`)
      await qc.invalidateQueries({ queryKey: key })
    } catch (err) {
      alert(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold">评论</h3>
      <div className="space-y-2">
        {isLoading && <p className="text-xs text-muted-foreground">加载中…</p>}
        {(data?.items ?? []).map((c) => (
          <div key={c.id} className="rounded-md border p-2.5 text-sm">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium">{c.author}</span>
              <span className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{new Date(c.created_at).toLocaleString()}</span>
                {canEdit && (
                  <button className="text-xs text-muted-foreground hover:text-destructive" onClick={() => void remove(c.id)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-muted-foreground">{c.body}</p>
          </div>
        ))}
      </div>
      {canEdit && (
        <form onSubmit={onSubmit} className="space-y-2">
          <Textarea value={body} onChange={(e) => setBody(e.target.value)} autoComplete="off" placeholder="写评论…" />
          <ErrorNotification message={error} />
          <Button type="submit" size="sm" disabled={!body.trim()}>
            发表评论
          </Button>
        </form>
      )}
    </div>
  )
}
