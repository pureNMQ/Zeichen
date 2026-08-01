import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, UserRound } from 'lucide-react'
import { api, ApiError, type MemberRow, type Role } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

function AddMemberDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.post('/members', { username: username.trim(), role })
      setUsername('')
      setRole('member')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加成员</DialogTitle>
          <DialogDescription>成员首次登录时设置密码</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="member-username">登录账号</Label>
            <Input
              id="member-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              maxLength={64}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label>角色</Label>
            <Select value={role} onValueChange={(v) => setRole(v as Role)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">成员</SelectItem>
                <SelectItem value="admin">管理员</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '添加中…' : '添加'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function RoleSelect({ member }: { member: MemberRow }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  async function changeRole(role: Role) {
    setError(null)
    try {
      await api.patch(`/members/${member.id}`, { role })
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改失败')
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Select value={member.role} onValueChange={changeRole} disabled={error !== null}>
        <SelectTrigger className="w-28">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="member">成员</SelectItem>
          <SelectItem value="admin">管理员</SelectItem>
        </SelectContent>
      </Select>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  )
}

export function MembersPage() {
  const [addOpen, setAddOpen] = useState(false)
  const {
    data: members,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['members'],
    queryFn: () => api.get<MemberRow[]>('/members'),
  })
  const qc = useQueryClient()
  const [removeError, setRemoveError] = useState<string | null>(null)

  async function remove(id: string, username: string) {
    if (!window.confirm(`移除成员 ${username}?其项目权限将一并清除`)) return
    setRemoveError(null)
    try {
      await api.delete(`/members/${id}`)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '移除失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">成员管理</h1>
          <p className="text-sm text-muted-foreground">工作区成员(人类账号),管理员专属</p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          添加成员
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {removeError && <p className="text-sm text-destructive">{removeError}</p>}
      {!isLoading && members?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <UserRound className="h-8 w-8" />
            <p className="text-sm">暂无成员</p>
          </CardContent>
        </Card>
      )}

      {members && members.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">成员列表</CardTitle>
            <CardDescription>共 {members.length} 人</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>账号</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>加入时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="font-medium">{m.username}</TableCell>
                    <TableCell>
                      <RoleSelect member={m} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(m.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void remove(m.id, m.username)}
                      >
                        <Trash2 className="h-4 w-4" />
                        <span className="sr-only">移除 {m.username}</span>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <AddMemberDialog open={addOpen} onOpenChange={setAddOpen} />
    </div>
  )
}
