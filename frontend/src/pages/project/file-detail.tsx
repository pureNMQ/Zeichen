import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { ErrorNotification } from '@/components/ui/notification'
import { api } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'
import { projectFileApiPath, projectFileContentUrl, type ProjectFileSummary } from '@/lib/project-files'

function FilePreview({ file }: { file: ProjectFileSummary }) {
  if (!file.preview_href) return null
  const url = projectFileContentUrl(file.project_id, file.id, true)
  if (file.media_type.startsWith('image/')) {
    return <img src={url} alt={file.name} className="max-h-[65vh] max-w-full rounded-md object-contain" />
  }
  if (file.media_type.startsWith('video/')) return <video controls preload="metadata" src={url} className="max-h-[65vh] max-w-full rounded-md" />
  if (file.media_type.startsWith('audio/')) return <audio controls preload="metadata" src={url} className="max-w-full" />
  return <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">打开预览</a>
}

export function ProjectFileDetailPage() {
  const { id = '' } = useParams()
  const { projectId } = useCurrentProject()
  const { data: file, isLoading, error, isError } = useQuery({
    queryKey: ['project-file', projectId, id],
    queryFn: () => api.get<ProjectFileSummary>(projectFileApiPath(projectId!, id)),
    enabled: !!projectId,
    retry: false,
  })

  if (isLoading) return <p role="status" className="text-sm text-muted-foreground">加载文件…</p>
  if (isError || !file || file.project_id !== projectId || file.id !== id) {
    return <ErrorNotification message={error instanceof Error ? error.message : '文件不存在或无访问权限'} />
  }
  return (
    <section className="space-y-4">
      <header className="space-y-2">
        <h1 className="break-all text-xl font-semibold">{file.name}</h1>
        <p className="text-sm text-muted-foreground">
          {file.media_type} · {new Intl.NumberFormat('zh-CN').format(file.size)} 字节
        </p>
        <a href={projectFileContentUrl(file.project_id, file.id)} download className="text-sm font-medium text-primary hover:underline">下载文件</a>
      </header>
      <FilePreview file={file} />
    </section>
  )
}
