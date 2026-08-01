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
}

export interface ProjectRow {
  id: string
  name: string
  created_at: string
  my_role: ProjectRole
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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    const detail =
      typeof body?.detail === 'string' ? body.detail : body?.detail?.[0]?.msg ?? '请求失败'
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
