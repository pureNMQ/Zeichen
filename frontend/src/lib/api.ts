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

export type DocumentType = 'wiki' | 'glossary' | 'api'

export type CodeSymbolKind = 'class' | 'struct' | 'interface' | 'enum' | 'function' | 'constructor' | 'method' | 'field' | 'property' | 'constant'

export interface CodeLibrary {
  id: string
  project_id: string
  name: string
  language: string
  package: string
  version: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface CodeEnumMember {
  position: number
  name: string
  assigned_value: string | null
  summary: string | null
}

export interface CodeSymbol {
  id: string
  library_id: string
  owner_symbol_id: string | null
  kind: CodeSymbolKind
  name: string
  qualified_name: string
  namespace: string | null
  summary: string
  remarks?: string
  accessibility: 'public' | 'protected' | 'internal' | 'private'
  source_declaration: string | null
  since_version: string | null
  deprecated: boolean
  definition: Record<string, unknown> & { members?: CodeEnumMember[] }
  members?: Array<{
    id: string
    kind: CodeSymbolKind
    name: string
    qualified_name: string
    summary: string
    signature: string
    deprecated: boolean
  }>
  signature: string
  revision: number
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface CodeTreeNode {
  node_kind: 'library' | 'namespace' | 'member_group' | 'symbol'
  id: string
  title: string
  language?: string
  package?: string
  symbol_kind?: CodeSymbolKind
  summary?: string
  signature?: string
  children: CodeTreeNode[]
}

export interface LibrarySymbolParameter {
  name: string
  type: string
  required?: boolean
  default_value?: string | null
  description?: string | null
}

export interface LibrarySymbolException {
  type: string
  description?: string | null
}

export type LibrarySymbolKind = 'class' | 'struct' | 'interface' | 'enum' | 'function' | 'constructor' | 'method' | 'field' | 'property' | 'constant' | 'enum_value'

export interface LibrarySymbol {
  id?: string
  document_id?: string
  owner_symbol_id?: string | null
  owner_symbol?: { symbol: string; kind: LibrarySymbolKind } | null
  members?: { document_id: string; symbol: string; kind: LibrarySymbolKind; summary: string }[]
  language: string
  package: string
  namespace?: string | null
  symbol: string
  kind: LibrarySymbolKind
  visibility?: string | null
  canonical_signature: string
  return_type?: string | null
  return_description?: string | null
  since_version?: string | null
  deprecated?: boolean
  parameters: LibrarySymbolParameter[]
  exceptions: LibrarySymbolException[]
}

export interface LibrarySymbolOption {
  id: string
  document_id: string
  language: string
  symbol: string
  kind: LibrarySymbolKind
  package: string
  namespace?: string | null
  canonical_signature: string
}

export interface LegacyCodeTreeNode {
  node_kind: 'package' | 'namespace' | 'member_group' | 'symbol'
  id: string
  title: string
  language?: string
  package?: string
  namespace?: string
  symbol_kind?: LibrarySymbolKind
  document?: DocumentRow
  children: LegacyCodeTreeNode[]
}

export interface DocumentRow {
  id: string
  node_kind: 'document'
  title: string
  doc_type: DocumentType
  content: string | null
  metadata: {
    endpoint?: { method: string; path: string }
    schema?: { fields?: { name: string; type: string; required?: boolean }[] }
  }
  library_symbol?: LibrarySymbol | null
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
  library_symbol?: LibrarySymbol | null
  created_by: string | null
  created_at: string
}

export const STATUS_LABEL: Record<WorkflowStatus, string> = {
  backlog: '待办',
  in_progress: '实现中',
  verifying: '验收中',
  done: '已完成',
  cancelled: '已取消',
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 8000)
  let resp: Response
  try {
    resp = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
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
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
