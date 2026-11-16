import { useCallback } from 'react'

import type { CompletionCandidate, CompletionLookup } from '@/components/markdown-composer'
import { api, type Page } from '@/lib/api'
import { projectFileContentUrl, type ProjectFileSummary } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'

function isScopedCandidate(projectId: string, candidate: CompletionCandidate) {
  const resource = candidate.kind === 'wiki' ? 'wiki'
    : candidate.kind === 'requirement' ? 'requirements'
      : 'people'
  return candidate.href === projectResourceHref(projectId, resource, candidate.id)
}

export function useProjectCompletion(projectId: string | null): CompletionLookup {
  return useCallback(async (mode, query, signal) => {
    if (!projectId) return []
    const scopedId = projectId
    const project = `/projects/${encodeURIComponent(scopedId)}`
    const q = query.slice(0, 200)

    async function textCandidates(): Promise<CompletionCandidate[]> {
      if (mode === 'image') return []
      const params = new URLSearchParams({ mode, q })
      const result = await api.get<{ items: CompletionCandidate[] }>(`${project}/completions?${params}`, signal)
      return result.items.filter((candidate) => isScopedCandidate(scopedId, candidate))
    }

    async function fileCandidates(): Promise<CompletionCandidate[]> {
      if (mode === 'people') return []
      const params = new URLSearchParams({ query: q, limit: '20' })
      if (mode === 'image') params.set('images_only', 'true')
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
    }

    const [text, files] = await Promise.all([textCandidates(), fileCandidates()])
    return [...text, ...files]
  }, [projectId])
}
