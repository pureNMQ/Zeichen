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

export interface UserIdentity {
  id: string
  username: string
  nickname?: string | null
  display_name?: string
  avatar?: string | null
}

export interface Me extends UserIdentity {
  is_agent: boolean
  workspace_role: Role | null
}

export interface LoginResponse {
  needs_password: boolean
  user?: Me
}

export interface MemberRow extends UserIdentity {
  role: Role
  created_at: string
  is_bootstrap: boolean
  is_self: boolean
  has_password: boolean
  agent: MemberAgentSummary | null
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
  description?: string
  member_count?: number
  owner_name?: string | null
  created_at: string
  my_role: ProjectRole
}

export interface ProjectMemberCandidate extends UserIdentity {
  is_agent: boolean
  workspace_role: Role
}

export interface ProjectMemberRow extends ProjectMemberCandidate {
  role: ProjectRole
  is_current_user?: boolean
}

export interface MemberAgentSummary {
  id: string
  username: string
  nickname: string | null
  display_name: string
  created_at: string
  active_keys: number
}

export interface MyAgentKey {
  id: string
  note: string | null
  created_at: string
  revoked_at: string | null
}

export interface MyAgentDetail extends UserIdentity {
  created_at: string
  active_keys: number
  keys: MyAgentKey[]
}

export type WorkflowStatus = 'pending' | 'backlog' | 'in_progress' | 'verifying' | 'done' | 'cancelled'
// 需求六态(含待确认/验收中,验收上移需求);任务四态(无待确认/验收中,ADR 0003)
export type RequirementStatus = Exclude<WorkflowStatus, never>
export type TaskStatus = Exclude<WorkflowStatus, 'pending' | 'verifying'>

export const REQUIREMENT_STATUSES: RequirementStatus[] = ['pending', 'backlog', 'in_progress', 'verifying', 'done', 'cancelled']
export const EXECUTION_REQUIREMENT_STATUSES: RequirementStatus[] = ['backlog', 'in_progress', 'verifying', 'done', 'cancelled']
export const TASK_STATUSES: TaskStatus[] = ['backlog', 'in_progress', 'done', 'cancelled']

export interface RequirementRow {
  /** 实体短码(ADR 0002):REQ-n */
  id: string
  title: string
  description: string | null
  status: RequirementStatus
  project_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  task_count: number
  participants?: { id: string; name: string; avatar?: string | null }[]
  blocked_by?: { id: string; title: string; status: RequirementStatus }[]
  blocks?: { id: string; title: string; status: RequirementStatus }[]
  blocked?: boolean
  version?: number
  done_task_count?: number
}

export interface TaskRow {
  /** 项目内稳定任务短码 REQ-n-Tm。 */
  version?: number
  id: string
  title: string
  description: string | null
  status: TaskStatus
  project_id: string
  requirement_id: string | null // 必挂需求(ADR 0003);旧数据直查可为空,UI 仍容忍
  assignee_id: string | null
  assignee: string | null
  assignee_username?: string | null
  assignee_avatar?: string | null
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
  author_avatar?: string | null
  created_at: string
}

export interface ActivityRow {
  id: string
  target_type: string
  target_id: string
  actor_id: string | null
  actor: string
  actor_avatar?: string | null
  action: string
  summary: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

// 个人筛选视图(T3):仅类型,运行期擦除;运行时符号见页面/组件实现
export type FilterViewMode = 'board' | 'list'

export interface FilterCriteria {
  participated_by_me?: boolean
  statuses?: string[]
  updated_within_days?: number
  keyword?: string
  assignee_id?: string
  view_mode?: FilterViewMode
}

export interface FilterViewRow {
  id: string
  project_id: string
  user_id: string
  entity_type: 'requirement' | 'task'
  name: string
  criteria: FilterCriteria
  created_at: string
  updated_at: string
}

export type DocumentType = 'wiki'

export type RepositoryVcsType = 'git' | 'svn' | 'other'

export interface RepositoryRow {
  id: string
  project_id: string
  name: string
  vcs_type: RepositoryVcsType
  other_vcs_type: string | null
  url: string
  description: string | null
  default_branch: string | null
  created_by: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

// REQ-59:溯源标识(人名或 agent 名+其主人,ADR 0004)
export interface AuthorIdentity {
  id: string
  username: string
  nickname: string | null
  is_agent: boolean
  owner: { id: string; username: string; nickname: string | null } | null
}

// REQ-59:[[双链]]聚合(outgoing 含断链;incoming=谁链我)
export interface WikiLinkOutgoing {
  raw_text: string
  display: string | null
  section: string | null
  to_code: string | null
  to_title: string | null
  broken: boolean
}

export interface WikiLinkIncoming {
  from_code: string
  from_title: string
  raw_text: string
  display: string | null
  section: string | null
}

export interface WikiLinks {
  outgoing: WikiLinkOutgoing[]
  incoming: WikiLinkIncoming[]
  broken_count: number
}

export interface DocumentRow {
  id: string
  node_kind: 'document'
  title: string
  doc_type: DocumentType
  content: string | null
  metadata: Record<string, unknown>
  project_id: string
  created_by: string | null
  author: AuthorIdentity | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  parent_id: string | null
  has_children: boolean
  links?: WikiLinks
  reference_warning?: { count: number; items: { raw_text: string; reason: string; display: string | null }[] }
}

export type DocumentNode = DocumentRow

// REQ-59:INDEX 投影行(与检索结果同构)
export interface WikiIndexRow {
  id: string
  title: string
  doc_kind: string | null
  summary: string
  missing_summary: boolean
  updated_at: string
  author: AuthorIdentity | null
}

export interface WikiIndexSection {
  kind: string | null
  label: string
  items: WikiIndexRow[]
}

export interface WikiIndex {
  project_id: string
  total: number
  sections: WikiIndexSection[]
  lint: {
    missing_kind: { id: string; title: string }[]
    missing_summary: { id: string; title: string }[]
    broken_links: { from: string; from_title: string | null; raw_text: string }[]
  }
}

export interface DocumentVersionRow {
  id: string
  version_no: number
  title: string
  content: string
  metadata: DocumentRow['metadata']
  created_by: string | null
  author: AuthorIdentity | null
  created_at: string
}

export const STATUS_LABEL: Record<WorkflowStatus, string> = {
  pending: '待确认',
  backlog: '待办',
  in_progress: '实现中',
  verifying: '验收中',
  done: '已完成',
  cancelled: '已取消',
}

export interface NotificationRow {
  id: string
  target_type: string
  target_id: string
  action: string
  summary: string | null
  actor_id: string | null
  read: boolean
  created_at: string
}

export interface AttachmentRow {
  id: string
  target_type: string
  target_id: string
  file_name: string
  size: number
  created_by: string | null
  created_at: string
  deleted_at: string | null
}

// 短码跨项目消歧(REQ-55):全局短码端点附带当前项目,后端在指定项目内解析。
// 显式 projectId 优先(实体行自带 project_id,最精确);否则回退当前项目(localStorage)。
export function withProject(path: string, projectId?: string | null): string {
  const pid = projectId ?? localStorage.getItem('zeichen.currentProjectId')
  if (!pid) return path
  return `${path}${path.includes('?') ? '&' : '?'}project_id=${encodeURIComponent(pid)}`
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 8000)
  let resp: Response
  try {
    resp = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
      ...options,
      signal: options.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal,
    })
  } finally {
    window.clearTimeout(timeout)
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    const detail =
      typeof body?.message === 'string'
        ? body.message
        : typeof body?.detail === 'string'
          ? body.detail
          : body?.detail?.[0]?.msg ?? (resp.status >= 500 ? `服务器暂时无法处理请求（HTTP ${resp.status}）` : `请求失败（HTTP ${resp.status}）`)
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  upload: <T>(path: string, body: FormData | File) => {
    const form = body instanceof FormData ? body : (() => { const f = new FormData(); f.append('file', body); return f })()
    return request<T>(path, { method: 'POST', body: form })
  },
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
