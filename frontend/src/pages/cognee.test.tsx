import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ErrorNotification, NotificationProvider } from '@/components/ui/notification'
import { CogneePage } from '@/pages/cognee'

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { ApiError, api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }
})

import { api } from '@/lib/api'

const configuration = {
  llm_provider: 'custom',
  llm_model: 'model-a',
  llm_endpoint: 'https://llm.example.test',
  llm_api_key_configured: true,
  llm_api_key_display: 'sec********alue',
  llm_api_key_source: 'managed' as const,
  embedding_provider: 'fastembed',
  embedding_model: 'embedding-a',
  embedding_dimensions: 384,
  pending_restart: true,
  updated_at: '2026-08-12T00:00:00Z',
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NotificationProvider><CogneePage /></NotificationProvider>
    </QueryClientProvider>,
  )
}

describe('CogneePage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('writes a changed configuration without sending an omitted API key', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => path === '/cognee/configuration'
      ? Promise.resolve(configuration)
      : Promise.resolve({ runtime: { availability: 'reachable', detail: null, checked_at: '2026-08-13T00:00:00Z' }, latest_restart: null }))
    vi.mocked(api.put).mockResolvedValue({ ...configuration, llm_model: 'model-b' })
    const user = userEvent.setup()
    renderPage()

    const model = await screen.findByLabelText('语言模型')
    await user.clear(model)
    await user.type(model, 'model-b')
    await user.click(screen.getByRole('button', { name: '保存配置' }))

    expect(api.put).toHaveBeenCalledWith('/cognee/configuration', expect.objectContaining({ llm_model: 'model-b' }))
    expect(vi.mocked(api.put).mock.calls[0][1]).not.toHaveProperty('llm_api_key')
  })

  it('hints the provider-qualified model format on the model input', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => path === '/cognee/configuration'
      ? Promise.resolve(configuration)
      : Promise.resolve({ runtime: { availability: 'reachable', detail: null, checked_at: '2026-08-13T00:00:00Z' }, latest_restart: null }))
    renderPage()

    const model = await screen.findByLabelText('语言模型')
    expect(model).toHaveAttribute('placeholder', 'provider/model，如 deepseek/deepseek-v4-flash')
  })

  it('requires a confirmation dialog before submitting a restart job', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => path === '/cognee/configuration'
      ? Promise.resolve(configuration)
      : Promise.resolve({ runtime: { availability: 'reachable', detail: null, checked_at: '2026-08-13T00:00:00Z' }, latest_restart: null }))
    vi.mocked(api.post).mockResolvedValue({ job: { id: 'r1', status: 'queued', error: null, created_at: '2026-08-12T00:00:00Z', started_at: null, finished_at: null } })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: '重启 Cognee' }))
    expect(screen.getByRole('dialog', { name: '确认重启 Cognee？' })).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '确认重启' }))
    expect(api.post).toHaveBeenCalledWith('/cognee/configuration/restarts', { confirmed: true })
  })

  it('shows a recoverable error instead of an endless loading state when configuration loading fails', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('配置接口不可用'))
    renderPage()

    expect(await screen.findByText('无法加载 Cognee 配置。')).toBeInTheDocument()
    expect(screen.queryByText('正在加载 Cognee 配置…')).not.toBeInTheDocument()
  })

  it('shows actual service availability and the absence of restart history', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => path === '/cognee/configuration'
      ? Promise.resolve(configuration)
      : Promise.resolve({ runtime: { availability: 'unreachable', detail: '无法连接 Cognee 服务', checked_at: '2026-08-13T00:00:00Z' }, latest_restart: null }))
    renderPage()

    expect(await screen.findByText('服务状态：')).toBeInTheDocument()
    expect(screen.getByText('不可达')).toBeInTheDocument()
    expect(screen.getByText('无法连接 Cognee 服务')).toBeInTheDocument()
    expect(screen.getByText('尚无重启记录')).toBeInTheDocument()
  })

  it('shows a masked managed API key and retains it when blank', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => path === '/cognee/configuration'
      ? Promise.resolve(configuration)
      : Promise.resolve({ runtime: { availability: 'reachable', detail: null, checked_at: '2026-08-13T00:00:00Z' }, latest_restart: null }))
    renderPage()

    const key = await screen.findByLabelText('语言模型 API 密钥（留空以保留现有密钥）')
    expect(key).toHaveValue('')
    expect(key).toHaveAttribute('placeholder', 'sec********alue')
  })

  it('shows a masked deployment API key', async () => {
    vi.mocked(api.get).mockImplementation((path: string) => path === '/cognee/configuration'
      ? Promise.resolve({ ...configuration, llm_api_key_display: 'sk-***************9f2a', llm_api_key_source: 'deployment' as const })
      : Promise.resolve({ runtime: { availability: 'reachable', detail: null, checked_at: '2026-08-13T00:00:00Z' }, latest_restart: null }))
    renderPage()

    expect(await screen.findByPlaceholderText('sk-***************9f2a')).toBeInTheDocument()
  })

  it('dismisses a configuration error notification after the request recovers', async () => {
    function NotificationHarness({ message }: { message: string | null }) {
      return <ErrorNotification message={message} />
    }

    const view = render(
      <NotificationProvider><NotificationHarness message="无法加载 Cognee 配置" /></NotificationProvider>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载 Cognee 配置')

    view.rerender(<NotificationProvider><NotificationHarness message={null} /></NotificationProvider>)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
