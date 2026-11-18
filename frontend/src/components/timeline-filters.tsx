import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export type TimelineFilters = Partial<Record<'keyword' | 'kind' | 'actor_id' | 'source_task' | 'from_at' | 'to_at', string>>
export type TimelineTask = { id: string; title: string }
type Actor = { id: string; name: string }

export function TimelineFilterForm({ actors, tasks, onApply }: {
  actors: Actor[]; tasks: TimelineTask[]; onApply: (filters: TimelineFilters) => void
}) {
  const [applied, setApplied] = useState(false)
  const [start, setStart] = useState('')
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    const filters: TimelineFilters = {}
    for (const key of ['keyword', 'kind', 'actor_id', 'source_task', 'from_at', 'to_at'] as const) {
      const value = String(fields.get(key) ?? '').trim()
      if (value) filters[key] = key === 'from_at' || key === 'to_at' ? new Date(value).toISOString() : value
    }
    setApplied(Object.keys(filters).length > 0)
    onApply(filters)
  }
  return <details className="rounded-md border px-3 py-2 text-sm">
    <summary className="cursor-pointer font-medium">{applied ? '筛选记录 · 已筛选' : '筛选记录'}</summary>
    <form onSubmit={submit} onReset={() => { setStart(''); setApplied(false); onApply({}) }}
      className="mt-3 grid gap-3 sm:grid-cols-2">
      <label>关键词<Input autoComplete="off" name="keyword" maxLength={256} /></label>
      <label>记录类型<select name="kind" className="block h-9 w-full rounded-md border bg-background px-2">
        <option value="">全部类型</option><option value="manual">人工记录</option><option value="system">系统记录</option>
      </select></label>
      <label>操作者<Input autoComplete="off" name="actor_id" list="timeline-filter-actors" placeholder="选择操作者或输入用户 ID" /></label>
      <datalist id="timeline-filter-actors">{actors.map(person => <option key={person.id} value={person.id} label={person.name} />)}</datalist>
      <label>来源任务<Input autoComplete="off" name="source_task" list="timeline-filter-tasks" placeholder="选择任务或输入短码" /></label>
      <datalist id="timeline-filter-tasks">{tasks.map(task => <option key={task.id} value={task.id} label={task.title} />)}</datalist>
      <label>开始时间<Input type="datetime-local" name="from_at" autoComplete="off" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>结束时间<Input type="datetime-local" name="to_at" autoComplete="off" min={start || undefined} /></label>
      <div className="flex gap-2"><Button size="sm" type="submit">应用筛选</Button>
        <Button size="sm" type="reset" variant="ghost">清除筛选</Button></div>
    </form>
  </details>
}
