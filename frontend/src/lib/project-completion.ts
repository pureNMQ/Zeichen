import { useCallback } from 'react'

import type { CompletionCandidate, CompletionLookup } from '@/components/markdown-composer'
import { api, type Page } from '@/lib/api'
import { projectFileContentUrl, type ProjectFileSummary } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'

function isScopedCandidate(projectId: string, candidate: CompletionCandidate) {
  if (candidate.kind === 'task') {
    const parent = /^(REQ-[1-9]\d*)-T[1-9]\d*$/.exec(candidate.id)?.[1]
    return !!parent && (candidate.href === projectResourceHref(projectId, 'tasks', candidate.id)
      || candidate.href === `${projectResourceHref(projectId, 'requirements', parent)}?task=${candidate.id}`)
  }
  const resource = candidate.kind === 'wiki' ? 'wiki'
    : candidate.kind === 'requirement' ? 'requirements'
    : candidate.kind === 'file' ? 'files'
      : 'people'
  return candidate.href === projectResourceHref(projectId, resource, candidate.id)
}

export function useProjectCompletion(projectId: string | null): CompletionLookup {
  return useCallback(async (mode, query, signal) => {
    if (!projectId) return []
    const scopedId = projectId
    const project = `/projects/${encodeURIComponent(scopedId)}`
    const q = query.slice(0, 200)

    if (mode !== 'image') {
      const params = new URLSearchParams({ mode, q })
      const result = await api.get<{ items: CompletionCandidate[] }>(`${project}/completions?${params}`, signal)
      return result.items.filter((candidate) => isScopedCandidate(scopedId, candidate))
    }

    const params = new URLSearchParams({ query: q, limit: '20', images_only: 'true' })
    const result = await api.get<Page<ProjectFileSummary>>(`/v2${project}/files?${params}`, signal)
    return result.items
      .filter((item) => item.project_id === scopedId && item.href === projectResourceHref(scopedId, 'files', item.id))
      .map((item) => ({
        id: item.id,
        label: item.name,
        kind: 'file',
        href: item.href,
        detail: item.media_type,
        thumbnailUrl: item.preview_href ? projectFileContentUrl(scopedId, item.id, true) : undefined,
      }))
  }, [projectId])
}
