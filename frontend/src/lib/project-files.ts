export type ProjectFileSummary = {
  id: string
  project_id: string
  name: string
  media_type: string
  size: number
  href: string
  preview_href: string | null
  download_href: string
}

const UUID = '[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}'
const PROJECT_FILE_PATH = new RegExp(`^/projects/(${UUID})/files/(${UUID})$`)

export function projectFileApiPath(projectId: string, fileId: string) {
  return `/v2/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`
}

export function projectFileContentUrl(projectId: string, fileId: string, inline = false) {
  return `/api${projectFileApiPath(projectId, fileId)}/content${inline ? '?inline=true' : ''}`
}

export function previewUrlForFileLink(href: string) {
  const match = PROJECT_FILE_PATH.exec(href)
  return match ? projectFileContentUrl(match[1], match[2], true) : null
}
