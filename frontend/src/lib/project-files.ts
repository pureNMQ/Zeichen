import type { ComposerUpload } from '@/components/markdown-composer'
import { api, ApiError } from '@/lib/api'
import { projectResourceHref } from '@/lib/project-links'

export type ProjectFileSummary = {
  id: string
  project_id: string
  name: string
  media_type: string
  size: number
  href: string
  preview_href: string | null
  download_href: string | null
}

export type FileTargetKind = 'requirements' | 'tasks'
export type FileAssociationTarget = FileTargetKind | 'project' | 'wiki'
export type StagedProjectFile = { file: File; requestId: string }

const UUID = '[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}'
const PROJECT_FILE_PATH = new RegExp(`^/projects/(${UUID})/files/(${UUID})$`)

export function projectFileApiPath(projectId: string, fileId: string) {
  return `/v2/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`
}

export function projectFileContentUrl(projectId: string, fileId: string, inline = false) {
  return `/api${projectFileApiPath(projectId, fileId)}/content${inline ? '?inline=true' : ''}`
}

export function fileAssociationQuery(targetKind: FileAssociationTarget, targetId: string) {
  return new URLSearchParams({ target_kind: targetKind, target_id: targetId })
}

export async function uploadAssociatedFile(
  projectId: string, targetKind: FileAssociationTarget, targetId: string, attempt: StagedProjectFile,
): Promise<void> {
  const saved = await uploadFileToProject(projectId, attempt.file, attempt.requestId, new AbortController().signal, () => {})
  await associateProjectFile(projectId, targetKind, targetId, saved.id)
}

export async function associateProjectFile(
  projectId: string, targetKind: FileAssociationTarget, targetId: string, fileId: string,
): Promise<void> {
  await api.put(`${projectFileApiPath(projectId, fileId)}/usage?${fileAssociationQuery(targetKind, targetId)}`, {})
}

export function previewUrlForFileLink(href: string) {
  const match = PROJECT_FILE_PATH.exec(href)
  return match ? projectFileContentUrl(match[1], match[2], true) : null
}
export async function uploadFileToProject(
  projectId: string,
  file: File,
  requestId: string,
  signal: AbortSignal,
  onProgress: (percent: number) => void,
): Promise<ProjectFileSummary> {
  const collection = `/v2${projectResourceHref(projectId, 'files')}`
  const limits = await api.get<{ max_file_bytes: number }>(`${collection}/limits`, signal)
  if (file.size > limits.max_file_bytes) {
    const limit = new Intl.NumberFormat('zh-CN').format(limits.max_file_bytes)
    throw new Error(`文件大小超过单文件上限（${limit} 字节）。`)
  }
  signal.throwIfAborted()
  const params = new URLSearchParams({ name: file.name, request_id: requestId })
  const saved = await new Promise<ProjectFileSummary>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api${collection}?${params}`)
    xhr.responseType = 'json'
    const abort = () => xhr.abort()
    signal.addEventListener('abort', abort, { once: true })
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(Math.floor(event.loaded / event.total * 100))
    })
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as ProjectFileSummary)
      else reject(new ApiError(xhr.status, xhr.response?.message ?? '文件上传失败，请重试。'))
    })
    xhr.addEventListener('error', () => reject(new Error('连接中断，文件上传失败。')))
    xhr.addEventListener('abort', () => reject(new DOMException('上传已取消', 'AbortError')))
    xhr.addEventListener('loadend', () => signal.removeEventListener('abort', abort))
    xhr.send(file)
  })
  if (!saved || saved.project_id !== projectId || saved.href !== projectResourceHref(projectId, 'files', saved.id)) {
    throw new Error('无法读取上传后的文件引用。')
  }
  return saved
}

export function projectFileUpload(projectId: string): ComposerUpload {
  return async (file, requestId, signal, onProgress) => {
    const saved = await uploadFileToProject(projectId, file, requestId, signal, onProgress)
    return { name: saved.name, href: saved.href, image: saved.media_type.startsWith('image/') && !!saved.preview_href }
  }
}
