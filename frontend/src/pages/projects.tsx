import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, FolderOpen } from 'lucide-react'
import { api, ApiError, type ProjectRow } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.post('/projects', { name: name.trim() })
      setName('')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
          <DialogDescription>项目成员授权将在项目详情页中配置</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-name">项目名称</Label>
            <Input
              id="project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={128}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ProjectsPage() {
  const { user } = useAuth()
  const [createOpen, setCreateOpen] = useState(false)
  const {
    data: projects,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<ProjectRow[]>('/projects'),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">项目</h1>
          <p className="text-sm text-muted-foreground">
            {user?.workspace_role === 'admin'
              ? '管理员可见全部项目'
              : '仅显示你已加入的项目'}
          </p>
        </div>
        {user?.workspace_role === 'admin' && (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            新建项目
          </Button>
        )}
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {!isLoading && projects?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <FolderOpen className="h-8 w-8" />
            <p className="text-sm">暂无项目</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {projects?.map((p) => (
          <Card key={p.id}>
            <CardHeader>
              <CardTitle className="text-base">
                <Link to={`/projects/${p.id}`} className="hover:text-primary">
                  {p.name}
                </Link>
              </CardTitle>
              <CardDescription>
                创建于 {new Date(p.created_at).toLocaleDateString()}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex items-center gap-2">
              <Badge variant="outline">{p.my_role}</Badge>
              <Link
                to={`/projects/${p.id}`}
                className="text-xs text-muted-foreground hover:text-primary"
              >
                基础信息 / 成员授权 →
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
