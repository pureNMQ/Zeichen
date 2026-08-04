export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type Role = 'admin' | 'member'
export type ProjectRole = 'owner' | 'editor' | 'viewer'

export interface Me {
  id: string
  username: string
  is_agent: boolean
  workspace_role: Role | null
}

export interface LoginResponse {
  needs_password: boolean
  user?: Me
}

export interface MemberRow {
  id: string
  username: string
  role: Role
  created_at: string
  is_bootstrap: boolean
  is_self: boolean
  has_password: boolean
}

export interface MemberCreateResponse extends MemberRow {
  password_setup_url: string
}

export interface PasswordSetupLinkResponse {
  password_setup_url: string
}

export interface ProjectRow {
  id: string
  name: string
  created_at: string
  my_role: ProjectRole
}

export interface ProjectMemberRow {
  id: string
  username: string
  is_agent: boolean
  role: ProjectRole
  is_current_user?: boolean
}

export interface ProjectGrant {
  project_id: string
  name: string
  role: ProjectRole
}

export interface AgentRow {
  id: string
  username: string
  created_at: string
  grants: ProjectGrant[]
  key_count: number
  active_keys: number
}

export interface AgentKey {
  id: string
  note: string | null
  created_at: string
  revoked_at: string | null
}

export type WorkflowStatus = 'backlog' | 'in_progress' | 'verifying' | 'done' | 'cancelled'
// 需求四态(ticket 09:删验收中);任务保留五态
export type RequirementStatus = Exclude<WorkflowStatus, 'verifying'>

export const REQUIREMENT_STATUSES: RequirementStatus[] = ['backlog', 'in_progress', 'done', 'cancelled']
export const TASK_STATUSES: WorkflowStatus[] = ['backlog', 'in_progress', 'verifying', 'done', 'cancelled']

export interface RequirementRow {
  id: string
  title: string
  description: string | null
  status: RequirementStatus
  project_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  task_count: number
}

export interface TaskRow {
  id: string
  title: string
  description: string | null
  status: WorkflowStatus
  project_id: string
  requirement_id: string | null
  assignee_id: string | null
  assignee: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface CommentRow {
  id: string
  target_type: string
  target_id: string
  body: string
  author_id: string
  author: string
  created_at: string
}

export interface ActivityRow {
  id: string
  target_type: string
  target_id: string
  actor_id: string | null
  actor: string
  action: string
  summary: string | null
  created_at: string
}

export interface ReferenceRow {
  id: string
  from_type: string
  from_id: string
  to_type: string
  to_id: string
  type: string
  created_by: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export const STATUS_LABEL: Record<WorkflowStatus, string> = {
  backlog: '待办',
  in_progress: '实现中',
  verifying: '验收中',
  done: '已完成',
  cancelled: '已取消',
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    const detail =
      typeof body?.message === 'string'
        ? body.message
        : typeof body?.detail === 'string'
          ? body.detail
          : body?.detail?.[0]?.msg ?? '请求失败'
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
