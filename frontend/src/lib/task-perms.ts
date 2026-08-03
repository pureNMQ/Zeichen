import type { Me, ProjectRole, TaskRow } from '@/lib/api'

/** 任务编辑权规则(ticket 09/10):已指派仅本人/工作区 admin/项目 owner,未指派任意编辑权。 */
export function canSetTaskStatus(task: TaskRow, user: Me | null, role: ProjectRole | null): boolean {
  if (!task.assignee_id) return role === 'editor' || role === 'owner'
  return user?.workspace_role === 'admin' || role === 'owner' || task.assignee_id === user?.id
}
