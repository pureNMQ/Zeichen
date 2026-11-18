import type { Me, ProjectRole, TaskRow } from '@/lib/api'

/** 状态、指派和删除共用服务端的任务所有权规则。 */
export function canManageTask(task: TaskRow, user: Me | null, role: ProjectRole | null): boolean {
  if (!user || (role !== 'editor' && role !== 'owner')) return false
  return !task.assignee_id || task.assignee_id === user.id || role === 'owner' || user.workspace_role === 'admin'
}
