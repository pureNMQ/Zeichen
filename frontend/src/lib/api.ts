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
  created_at: string
  my_role: ProjectRole
}

export interface ProjectMemberRow extends UserIdentity {
  is_agent: boolean
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

export interface CogneeConfiguration {
  llm_provider: string
  llm_model: string
  llm_endpoint: string | null
  llm_api_key_configured: boolean
  llm_api_key_display: string | null
  llm_api_key_source: 'managed' | 'deployment' | 'unconfigured'
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: number | null
  pending_restart: boolean
  updated_at: string
}

export interface CogneeRestartJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  status_label?: string
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface CogneeRuntimeStatus {
  runtime: {
    availability: 'reachable' | 'unreachable'
    detail: string | null
    checked_at: string
  }
  latest_restart: {
    status: CogneeRestartJob['status']
    status_label: string
    error: string | null
    requested_at: string
    finished_at: string | null
  } | null
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
  done_task_count?: number
}

export interface TaskBlockerSummary {
  id: string
  title: string
  status: TaskStatus
  resolved: boolean
}

export interface TaskRow {
  /** 实体短码(ADR 0002):TASK-n */
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
  blocked?: boolean
  blocked_by?: TaskBlockerSummary[]
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

export interface ReferenceRow {
  id: string
  from_type: string
  from_id: string
  to_type: string
  to_id: string
  type: string
  from_title?: string
  to_title?: string
  from_module?: string | null
  to_module?: string | null
  created_by: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

// 个人筛选视图(T3):仅类型,运行期擦除;运行时符号见页面/组件实现
export type FilterViewMode = 'board' | 'list'

export interface FilterCriteria {
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

export type DocumentType = 'wiki' | 'glossary'

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

export interface DocumentRow {
  id: string
  node_kind: 'document'
  title: string
  doc_type: DocumentType
  content: string | null
  metadata: Record<string, unknown>
  project_id: string
  created_by: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  parent_id: string | null
  directory_id: string | null
  has_children: boolean
  reference_warning?: { count: number; items: ReferenceRow[] }
}

export interface DocumentDirectoryRow {
  id: string
  node_kind: 'directory'
  name: string
  title: string
  module_type: Exclude<DocumentType, 'wiki'>
  project_id: string
  parent_id: string | null
  created_by: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  has_children: boolean
}

export type DocumentNode = DocumentRow | DocumentDirectoryRow

export interface DocumentVersionRow {
  id: string
  version_no: number
  title: string
  content: string
  metadata: DocumentRow['metadata']
  created_by: string | null
  created_at: string
}

export interface MemoryItem {
  id: string
  data?: string
  content?: string
  text?: string
  created_at?: string
  updated_at?: string
  external_metadata?: {
    source_id?: string
    source_name?: string
    source_kind?: string
    entity_type?: string
    entity_id?: string
  }
}

export interface MemorySession {
  id?: string
  session_id?: string
  business_session_id?: string
  source_id?: string
  source_name?: string
  source_kind?: string
  effective_status?: string
  status?: string
  last_activity_at?: string
  started_at?: string
  preview?: string
}

export interface MemorySessionDetail {
  session_id: string
  business_session_id: string
  source_name?: string
  status?: string
  qas: Array<{ time?: string; question?: string; answer?: string }>
  traces: Array<Record<string, unknown>>
}

export type MemoryImproveJobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'upstream_busy' | 'timed_out' | 'unknown'

export interface MemoryImproveJob {
  id: string
  project_id: string
  agent_id: string
  session_id: string
  status: MemoryImproveJobStatus
  result?: Record<string, unknown> | unknown[] | null
  error?: string | null
  created_at: string
  started_at?: string | null
  heartbeat_at?: string | null
  finished_at?: string | null
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

export type SearchDomain = 'requirement' | 'task' | 'document' | 'memory'

export interface SearchItem {
  domain: SearchDomain
  id: string
  project_id: string
  project_name: string
  title: string
  summary: string
  status?: string
  doc_type?: string
  kind?: string
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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 8000)
  let resp: Response
  try {
    resp = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
      ...options,
      signal: options.signal ?? controller.signal,
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
  get: <T>(path: string) => request<T>(path),
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
