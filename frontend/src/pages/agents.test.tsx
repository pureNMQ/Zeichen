import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AgentsPage } from '@/pages/agents'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      delete: vi.fn(),
    },
  }
})

import { api, type AgentRow } from '@/lib/api'

const rows: AgentRow[] = [
  {
    id: 'a1',
    username: 'planner',
    created_at: '2026-08-01T00:00:00Z',
    grants: [{ project_id: 'p1', name: '核心项目', role: 'editor' }],
    key_count: 2,
    active_keys: 1,
  },
  {
    id: 'a2',
    username: 'reader',
    created_at: '2026-08-02T00:00:00Z',
    grants: [],
    key_count: 0,
    active_keys: 0,
  },
]

function renderAgents() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AgentsPage />
    </QueryClientProvider>,
  )
}

describe('AgentsPage 卡片布局', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('以卡片展示项目授权、Key 状态和管理入口', async () => {
    vi.mocked(api.get).mockResolvedValue(rows)
    renderAgents()

    expect(await screen.findByText('planner')).toBeInTheDocument()
    expect(screen.getAllByTestId('agent-card')).toHaveLength(rows.length)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByText('核心项目 · editor')).toBeInTheDocument()
    expect(screen.getByText('1/2 有效')).toBeInTheDocument()
    expect(screen.getByText('暂无项目授权')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '管理 Key' })).toHaveLength(rows.length)
  })

  it('空列表显示占位卡片', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    renderAgents()

    expect(await screen.findByText('暂无 Agent')).toBeInTheDocument()
  })

  it('打开 Key 管理即加载有效 Key，并在吊销后立即隐藏', async () => {
    const keys = [
      { id: 'k1', note: '桌面客户端', created_at: '2026-08-03T00:00:00Z', revoked_at: null },
      { id: 'k2', note: '已吊销', created_at: '2026-08-02T00:00:00Z', revoked_at: '2026-08-03T00:00:00Z' },
    ]
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/agents') return Promise.resolve(rows)
      return Promise.resolve(keys)
    })
    vi.mocked(api.post).mockResolvedValue({ ok: true })
    const user = userEvent.setup()
    renderAgents()

    const manageButtons = await screen.findAllByRole('button', { name: '管理 Key' })
    expect(manageButtons).toHaveLength(rows.length)
    await user.click(manageButtons[0])

    expect(await screen.findByLabelText('有效 Key 列表')).toBeInTheDocument()
    expect(screen.getByText('桌面客户端')).toBeInTheDocument()
    expect(screen.queryByText('已吊销')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '查看已有 key' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '吊销 桌面客户端' }))
    expect(api.post).toHaveBeenCalledWith('/agents/a1/keys/k1/revoke')
    expect(screen.queryByText('桌面客户端')).not.toBeInTheDocument()
  })

  it('签发和回看都立即展示可复制、可吊销的 Key 明文', async () => {
    const issued = { id: 'k3', token: 'agent-key-plaintext' }
    const key = { id: 'k3', note: '自动化', created_at: '2026-08-03T00:00:00Z', revoked_at: null }
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/agents') return Promise.resolve(rows)
      return Promise.resolve([key])
    })
    vi.mocked(api.post).mockResolvedValue(issued)
    const user = userEvent.setup()
    renderAgents()

    const manageButtons = await screen.findAllByRole('button', { name: '管理 Key' })
    await user.click(manageButtons[0])
    await screen.findByLabelText('有效 Key 列表')
    await user.type(screen.getByPlaceholderText('备注（如：桌面客户端）'), '自动化')
    await user.click(screen.getByRole('button', { name: '签发' }))

    expect(await screen.findByText('agent-key-plaintext')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '吊销 自动化' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '回看 自动化' }))
    const verifyDialog = await screen.findByRole('dialog', { name: '验证管理员密码' })
    await user.type(screen.getByLabelText('当前密码'), 'admin-pass-1')
    await user.click(screen.getByRole('button', { name: '验证并显示' }))

    expect(api.post).toHaveBeenCalledWith('/agents/a1/keys/k3/reveal', { password: 'admin-pass-1' })
    expect(verifyDialog).not.toBeInTheDocument()
  })
})
