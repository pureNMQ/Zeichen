import { useInfiniteQuery } from '@tanstack/react-query'

import { api, type Page } from '@/lib/api'

export type WikiSummary = {
  id: string
  project_id: string
  parent_id: string | null
  version: number
  title: string
  summary: string | null
  category: string | null
  tags: string[]
}

export type WikiContent = Pick<WikiSummary, 'title' | 'summary' | 'category' | 'tags'> & { body: string }
export type WikiDocument = WikiSummary & WikiContent
export type WikiReceipt = Pick<WikiSummary, 'id' | 'project_id' | 'version'>
export type WikiScope = { projectId: string; url: string; canWrite: boolean }

export function useWikiList<T extends WikiSummary>(projectId: string, path: string, query: string, collection = 'list') {
  const list = useInfiniteQuery({
    queryKey: ['wiki-v2', projectId, collection, query],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ q: query, limit: '20' })
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<T>>(`${path}?${params}`, signal)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    retry: false,
  })
  return {
    ...list,
    documents: list.data?.pages.flatMap((page) => page.items)
      .filter((document) => document.project_id === projectId) ?? [],
  }
}

/** Present parent links within loaded pages while retaining entries whose parents are on other pages. */
export function orderWikiTree(documents: WikiSummary[]) {
  const byId = new Set(documents.map(({ id }) => id))
  const children = new Map<string | null, WikiSummary[]>()
  for (const document of documents) {
    const parent = document.parent_id && byId.has(document.parent_id) ? document.parent_id : null
    const siblings = children.get(parent) ?? []
    siblings.push(document)
    children.set(parent, siblings)
  }

  const ordered: { document: WikiSummary; depth: number }[] = []
  const visited = new Set<string>()
  function walk(root: WikiSummary) {
    const stack = [{ document: root, depth: 0 }]
    while (stack.length) {
      const item = stack.pop()!
      if (visited.has(item.document.id)) continue
      visited.add(item.document.id)
      ordered.push(item)
      const descendants = children.get(item.document.id) ?? []
      for (let index = descendants.length - 1; index >= 0; index--) {
        stack.push({ document: descendants[index], depth: item.depth + 1 })
      }
    }
  }
  for (const root of children.get(null) ?? []) walk(root)
  for (const document of documents) walk(document)
  return ordered
}
