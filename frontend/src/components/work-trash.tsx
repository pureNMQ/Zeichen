import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

type Kind = 'requirement' | 'task'
type Row = { id: string; title: string; deleted_at: string; requirement_id?: string }
type Detail = Row & { description: string | null; affected_tasks?: number }

export function WorkTrash({ projectId }: { projectId: string }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<Kind>('requirement')
  const [keyword, setKeyword] = useState('')
  const [cursor, setCursor] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const root = `/v2/projects/${projectId}/trash/work`
  const page = useQuery({
    queryKey: ['work-trash', projectId, kind, keyword, cursor],
    queryFn: () => api.get<{ items: Row[]; next_cursor: string | null }>(`${root}?${new URLSearchParams({
      kind, keyword, ...(cursor ? { cursor } : {}),
    })}`),
    enabled: open,
  })
  const detail = useQuery({
    queryKey: ['work-trash', projectId, kind, 'detail', selected],
    queryFn: () => api.get<Detail>(`${root}/${kind}/${selected}`),
    enabled: open && !!selected,
  })

  function resetPage() {
    setCursor(null)
    setSelected(null)
    setError(null)
  }

  async function restore(id: string) {
    setRestoring(true)
    setError(null)
    try {
      await api.post(`${root}/${kind}/${id}/restore`)
      resetPage()
      await Promise.all([
        client.invalidateQueries({ queryKey: ['work-trash', projectId] }),
        client.invalidateQueries({ queryKey: ['requirements', projectId] }),
        client.invalidateQueries({ queryKey: ['tasks', projectId] }),
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复失败，请重试')
    } finally {
      setRestoring(false)
    }
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>工作项回收站</Button>
      <ErrorNotification message={open ? (page.error?.message ?? detail.error?.message) : null} />
      <Dialog open={open} onOpenChange={(value) => { if (!restoring) { setOpen(value); resetPage() } }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>工作项回收站</DialogTitle>
            <DialogDescription>恢复需求时，随它隐藏的任务会重新显示。</DialogDescription>
          </DialogHeader>
          <div className="flex gap-2">
            <Button size="sm" variant={kind === 'requirement' ? 'default' : 'outline'} disabled={restoring}
              aria-pressed={kind === 'requirement'} onClick={() => { setKind('requirement'); resetPage() }}>需求</Button>
            <Button size="sm" variant={kind === 'task' ? 'default' : 'outline'} disabled={restoring}
              aria-pressed={kind === 'task'} onClick={() => { setKind('task'); resetPage() }}>任务</Button>
          </div>
          <Input autoComplete="off" aria-label="筛选工作项" placeholder="按标题或短码筛选" maxLength={256}
            disabled={restoring} value={keyword} onChange={(event) => { setKeyword(event.target.value); resetPage() }} />
          {page.isLoading && <p role="status">加载中…</p>}
          {page.isError && <Button variant="outline" onClick={() => void page.refetch()}>重试</Button>}
          {page.data?.items.length === 0 && <p className="text-sm text-muted-foreground">没有匹配的已删除工作项。</p>}
          {page.data?.items.map((item) => (
            <div key={item.id} className="space-y-2 rounded-md border p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{item.id} · {item.title}</p>
                  <p className="text-xs text-muted-foreground">删除于 {new Date(item.deleted_at).toLocaleString()}</p>
                </div>
                <Button size="sm" variant="outline" disabled={restoring} onClick={() => { setSelected(item.id); setError(null) }}>
                  查看
                </Button>
              </div>
              {selected === item.id && detail.data && (
                <>
                  {detail.data.description && <p className="whitespace-pre-wrap text-sm">{detail.data.description}</p>}
                  {detail.data.affected_tasks !== undefined && (
                    <p className="text-sm text-muted-foreground">{detail.data.affected_tasks} 个任务会重新显示</p>
                  )}
                  {detail.data.requirement_id && <p className="text-sm">所属需求 {detail.data.requirement_id}</p>}
                  {error && <p className="text-sm text-destructive">{error}</p>}
                  <Button size="sm" disabled={restoring} onClick={() => void restore(item.id)}>恢复</Button>
                </>
              )}
            </div>
          ))}
          <div className="flex gap-2">
            {cursor && <Button size="sm" variant="outline" onClick={resetPage}>返回首页</Button>}
            {page.data?.next_cursor && <Button size="sm" variant="outline" onClick={() => {
              setCursor(page.data.next_cursor); setSelected(null); setError(null)
            }}>下一页</Button>}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
