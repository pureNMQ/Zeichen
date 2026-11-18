import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Plus, Search, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { api, type Page } from '@/lib/api'
import { projectResourceHref } from '@/lib/project-links'
import type { WikiScope, WikiSummary } from '@/lib/project-wiki'
import { cn } from '@/lib/utils'

type DirectoryEntry = Pick<WikiSummary, 'id' | 'title' | 'parent_id' | 'project_id'>

export function WikiDirectory({ projectId, url, canWrite, selectedId, className, visibleOnMobile }: WikiScope & {
  selectedId: string | undefined
  className?: string
  visibleOnMobile: boolean
}) {
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const selectedLink = useRef<HTMLAnchorElement>(null)
  const base = projectResourceHref(projectId, 'wiki')
  const directory = useQuery({
    queryKey: ['wiki-v2', projectId, 'directory'],
    queryFn: async ({ signal }) => {
      const entries = new Map<string, DirectoryEntry>()
      let cursor: string | null = null
      // A parent can appear on a later page than its children.
      do {
        const params = new URLSearchParams({ limit: '100' })
        if (cursor) params.set('cursor', cursor)
        const page: Page<DirectoryEntry> = await api.get(`${url}?${params}`, signal)
        for (const entry of page.items) {
          if (entry.project_id === projectId) entries.set(entry.id, entry)
        }
        cursor = page.next_cursor
      } while (cursor)
      return entries
    },
    retry: false,
  })
  const entries = directory.data
  const children = useMemo(() => {
    const branches = new Map<string | null, DirectoryEntry[]>()
    for (const entry of entries?.values() ?? []) {
      const siblings = branches.get(entry.parent_id)
      if (siblings) siblings.push(entry)
      else branches.set(entry.parent_id, [entry])
    }
    return branches
  }, [entries])
  const query = filter.trim().toLowerCase()
  const matches = new Set<string>()
  if (query && entries) {
    for (const entry of entries.values()) {
      if (!entry.title.toLowerCase().includes(query) && !entry.id.toLowerCase().includes(query)) continue
      let id: string | null = entry.id
      while (id && !matches.has(id)) {
        matches.add(id)
        id = entries.get(id)?.parent_id ?? null
      }
    }
  }

  useEffect(() => {
    if (!selectedId || !entries) return
    const ancestors = new Set<string>()
    let parent = entries.get(selectedId)?.parent_id
    while (parent && !ancestors.has(parent)) {
      ancestors.add(parent)
      parent = entries.get(parent)?.parent_id
    }
    if (ancestors.size) setExpanded((current) => new Set([...current, ...ancestors]))
  }, [entries, selectedId])

  useEffect(() => {
    const link = selectedLink.current
    if (link?.getClientRects().length) link.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [expanded, entries, selectedId, visibleOnMobile, query])

  function toggle(id: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function visibleChildren(parent: string | null) {
    const branch = children.get(parent) ?? []
    return query ? branch.filter((entry) => matches.has(entry.id)) : branch
  }

  function renderBranch(branch: DirectoryEntry[], nested = false) {
    return <ul className={nested ? 'ms-3 border-s border-border ps-3' : 'space-y-0.5'}>
      {branch.map((entry) => {
        const descendants = visibleChildren(entry.id)
        const open = Boolean(query) || expanded.has(entry.id)
        const selected = entry.id === selectedId
        const href = projectResourceHref(projectId, 'wiki', entry.id)
        return <li key={entry.id}>
          <div className={cn('flex min-w-24 items-center rounded-md hover:bg-muted', selected && 'bg-accent text-accent-foreground')}>
            {descendants.length > 0 && !query ? (
              <button type="button" aria-label={`${open ? '折叠' : '展开'}${entry.title}`} aria-expanded={open}
                className="grid size-7 shrink-0 place-items-center rounded text-muted-foreground hover:bg-background focus-visible:outline-ring"
                onClick={() => toggle(entry.id)}>
                <ChevronRight aria-hidden="true" className={cn('size-4', open && 'rotate-90')} />
              </button>
            ) : <span className="grid size-7 shrink-0 place-items-center text-muted-foreground" aria-hidden="true">
              {descendants.length > 0 && <ChevronRight className="size-4 rotate-90" />}
            </span>}
            <Link to={href} ref={selected ? selectedLink : undefined} aria-current={selected ? 'page' : undefined}
              state={{ focusWikiHeading: true }}
              className={cn('min-w-0 flex-1 wrap-anywhere rounded py-1.5 pe-2 text-sm focus-visible:outline-ring', selected && 'font-semibold')}>
              {entry.title}
            </Link>
          </div>
          {open && descendants.length > 0 && renderBranch(descendants, true)}
        </li>
      })}
    </ul>
  }

  const roots = visibleChildren(null)
  const newHref = `${base}?mode=new`
  const trashHref = `${base}?mode=trash`
  return (
    <aside className={cn('min-h-0 flex-col bg-muted/20', className)} aria-label="Wiki 目录" id="wiki-directory">
      <div className="shrink-0 space-y-2 border-b px-3 py-3">
        <div className="flex min-h-8 items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Wiki 目录</h2>
          {canWrite && <div className="flex items-center gap-1">
            <Button asChild size="icon-sm" variant="ghost">
              <Link to={newHref} aria-label="新建 Wiki" title="新建 Wiki">
                <Plus aria-hidden="true" />
              </Link>
            </Button>
            <Button asChild size="icon-sm" variant="ghost">
              <Link to={trashHref} aria-label="回收站" title="回收站">
                <Trash2 aria-hidden="true" />
              </Link>
            </Button>
          </div>}
        </div>
        <div className="relative">
          <Search aria-hidden="true" className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input autoComplete="off" aria-label="搜索 Wiki" placeholder="搜索 Wiki" maxLength={256} value={filter}
            className="ps-8" onChange={(event) => setFilter(event.currentTarget.value)} />
        </div>
      </div>
      <nav aria-label="Wiki 文档树" className="min-h-0 flex-1 overflow-auto p-2">
        {directory.isLoading && <p role="status" className="px-2 py-1 text-sm text-muted-foreground">加载目录…</p>}
        <ErrorNotification message={directory.error?.message} />
        {directory.isError && <Button type="button" size="sm" variant="outline" onClick={() => void directory.refetch()}>重试加载目录</Button>}
        {!directory.isLoading && !directory.isError && !roots.length && (
          <p className="px-2 py-1 text-sm text-muted-foreground">{query ? '没有符合条件的 Wiki' : '暂无 Wiki'}</p>
        )}
        {renderBranch(roots)}
      </nav>
    </aside>
  )
}
