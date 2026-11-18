import { useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { api, ApiError, withProject, type Page, type RequirementRow } from '@/lib/api'

export function RequirementDependencies({ item, canEdit }: { item: RequirementRow; canEdit: boolean }) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const qc = useQueryClient()
  const base = `/projects/${item.project_id}/requirements`
  const deps = item.blocked_by ?? []
  const candidates = useInfiniteQuery({
    queryKey: ['dependency-candidates', item.project_id, keyword], enabled: open && canEdit,
    queryFn: ({pageParam, signal}) => {
      const params = new URLSearchParams({ limit: '20' })
      if (keyword.trim()) params.set('keyword', keyword.trim())
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<RequirementRow>>(`${base}?${params}`, signal)
    },
    initialPageParam: null as string | null, getNextPageParam: p => p.next_cursor ?? undefined,
  })
  async function update(ids: string[]) {
    if (busy) return
    setBusy(true); setError('')
    try {
      await api.patch(withProject(`/requirements/${item.id}`, item.project_id), { blocked_by: ids, expected_blocked_by: deps.map(d => d.id) })
      await Promise.all(['requirement','requirements','requirement-timeline'].map(key => qc.invalidateQueries({ queryKey: [key] })))
      setOpen(false)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        await qc.invalidateQueries({ queryKey: ['requirement',item.id] })
        setError(e.message + '。请核对前置需求后重新选择。')
      } else setError(e instanceof Error ? e.message : '更新前置需求失败')
    }
    finally { setBusy(false) }
  }
  if (!canEdit && !deps.length && !item.blocks?.length) return null
  return <section className="space-y-2 text-sm" aria-label="前置需求">
    <div className="flex flex-wrap items-center gap-2">
      {!!deps.length && <span className="text-muted-foreground">前置需求</span>}
      {deps.map(dep => <div className="flex items-center gap-1" key={dep.id}>
        <Link className="underline" to={base+'/'+dep.id}>{dep.id} · {dep.title}</Link>
        <span className="text-xs text-muted-foreground">{dep.status === 'done' ? '已完成' : '等待完成'}</span>
        {open && <Button variant="ghost" size="sm" disabled={busy} aria-label={`移除前置需求 ${dep.id}`}
          onClick={() => void update(deps.filter(d => d.id !== dep.id).map(d => d.id))}>移除</Button>}
      </div>)}
      {canEdit && <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '收起' : deps.length ? '管理前置需求' : '添加前置需求'}</Button>}
    </div>
    {!!item.blocks?.length && <div className="flex flex-wrap items-center gap-2">
      <span className="text-muted-foreground">后续需求</span>
      {item.blocks.map(dep => <Link key={dep.id} className="underline" to={base + '/' + dep.id}>{dep.id} · {dep.title}</Link>)}
    </div>}
    {open && <div className="max-w-lg space-y-1 rounded-md border p-2">
      <Input aria-label="搜索前置需求" placeholder="按标题或编号搜索" autoComplete="off" value={keyword} onChange={e => setKeyword(e.target.value)} />
      {candidates.data?.pages.flatMap(p => p.items).filter(r => r.id !== item.id && !deps.some(d => d.id === r.id)).map(r =>
        <Button type="button" className="block w-full truncate text-left" key={r.id} size="sm" variant="ghost" disabled={busy}
          onClick={() => void update([...deps.map(d => d.id), r.id])}>{r.id} · {r.title}</Button>)}
      {candidates.hasNextPage && <Button variant="ghost" size="sm" onClick={() => void candidates.fetchNextPage()}>加载更多</Button>}
    </div>}
    <ErrorNotification message={error || (open ? candidates.error?.message : null)} />
  </section>
}
