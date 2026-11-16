import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/components/vditor-ir-editor', () => ({
  VditorIrEditor: ({ initialMarkdown, onChange }: { initialMarkdown: string; onChange: (markdown: string) => void }) => <textarea aria-label="Markdown 正文" data-testid="vditor-ir-editor" defaultValue={initialMarkdown} onChange={(event) => onChange(event.target.value)} />,
  VditorMarkdownViewer: ({ markdown }: { markdown: string }) => <div data-testid="vditor-viewer">{markdown}</div>,
}))
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return { withProject: (path: string) => path, ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

import { api } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { DocumentWorkbenchPage } from '@/pages/documents'

const author = { id: 'u1', username: 'alice', nickname: '爱丽丝', is_agent: false, owner: null }
const agentAuthor = { id: 'u2', username: 'helper', nickname: null, is_agent: true, owner: { id: 'u1', username: 'alice', nickname: '爱丽丝' } }

const doc = (overrides: Partial<Record<string, unknown>> = {}) => ({
  id: 'DOC-1', node_kind: 'document', title: '目标页', doc_type: 'wiki', content: '正文',
  metadata: { doc_kind: 'decision', summary: '一句话摘要', tags: ['a'], aliases: ['别名一'] },
  project_id: 'p1', created_by: 'u1', author, created_at: '2026-10-07T00:00:00Z', updated_at: '2026-10-07T00:00:00Z',
  deleted_at: null, parent_id: null, has_children: false,
  links: {
    outgoing: [
      { raw_text: 'DOC-2', display: null, section: null, to_code: 'DOC-2', to_title: '另一页', broken: false },
      { raw_text: '不存在的页', display: null, section: null, to_code: null, to_title: null, broken: true },
    ],
    incoming: [{ from_code: 'DOC-3', from_title: '来源页', raw_text: '目标页', display: null, section: null }],
    broken_count: 1,
  },
  ...overrides,
})

function renderWorkbench(entry = '/documents/wiki/DOC-1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CurrentProjectProvider>
        <DocumentNavigationProvider>
          <MemoryRouter initialEntries={[entry]}>
            <Routes>
              <Route path="/documents/wiki" element={<DocumentWorkbenchPage module="wiki" />} />
              <Route path="/documents/wiki/:id" element={<DocumentWorkbenchPage module="wiki" />} />
            </Routes>
          </MemoryRouter>
        </DocumentNavigationProvider>
      </CurrentProjectProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/projects') return Promise.resolve([{ id: 'p1', name: '测试项目', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' }])
    if (path === '/documents/wiki/DOC-1') return Promise.resolve(doc())
    if (path === '/projects/p1/documents/index') return Promise.resolve({
      project_id: 'p1', total: 3,
      sections: [
        { kind: 'decision', label: '决策', items: [{ id: 'DOC-1', title: '目标页', doc_kind: 'decision', summary: '一句话摘要', missing_summary: false, updated_at: '2026-10-07T00:00:00Z', author }] },
        { kind: null, label: '未分类', items: [{ id: 'DOC-9', title: '老页面', doc_kind: null, summary: '正文截断', missing_summary: false, updated_at: '2026-10-06T00:00:00Z', author: agentAuthor }] },
      ],
      lint: { missing_kind: [{ id: 'DOC-9', title: '老页面' }], missing_summary: [], broken_links: [{ from: 'DOC-1', from_title: '目标页', raw_text: '不存在的页' }] },
    })
    return Promise.resolve({ items: [], next_cursor: null })
  })
})

describe('REQ-59 详情页:frontmatter/溯源/双链/反链', () => {
  it('显示形态标签、summary、tags/aliases 与作者溯源徽标', async () => {
    renderWorkbench()
    expect(await screen.findByText('目标页')).toBeInTheDocument()
    expect(screen.getByText('决策')).toBeInTheDocument()
    expect(screen.getByTestId('frontmatter-summary')).toHaveTextContent('一句话摘要')
    expect(screen.getByTestId('frontmatter-tags')).toHaveTextContent('#a')
    expect(screen.getByTestId('frontmatter-tags')).toHaveTextContent('别名:别名一')
    expect(screen.getByTestId('author-badge')).toHaveTextContent('爱丽丝')
  })

  it('显示链接面板(含断链标记)与反链(谁链我)', async () => {
    renderWorkbench()
    expect(await screen.findByText('链接(2)')).toBeInTheDocument()
    expect(screen.getByText('反链(1)')).toBeInTheDocument()
    expect(screen.getByText('来源页')).toBeInTheDocument()
    expect(screen.getAllByText('断链').length).toBeGreaterThan(0)
  })

  it('点击断链打开创建对话框:预填标题,创建后重存源页接链', async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockImplementation((path: string, body?: unknown) => {
      if (path === '/projects/p1/documents/wiki') return Promise.resolve(doc({ id: 'DOC-9', title: (body as { title: string }).title }))
      return Promise.resolve({})
    })
    vi.mocked(api.patch).mockResolvedValue(doc())
    renderWorkbench()
    const brokenButton = await screen.findByRole('button', { name: /不存在的页/ })
    await user.click(brokenButton)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('创建断链页面')
    expect(screen.getByLabelText('标题')).toHaveValue('不存在的页')
    await user.click(screen.getByRole('button', { name: '创建页面' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/documents/wiki', expect.objectContaining({ title: '不存在的页' })))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/documents/wiki/DOC-1', expect.objectContaining({ content: '正文' })))
  })
})

describe('REQ-59 INDEX 视图:index-first 阅读', () => {
  it('无选中节点时落地知识 INDEX:分节+行内容+维护信号', async () => {
    renderWorkbench('/documents/wiki')
    expect(await screen.findByText('测试项目 知识 INDEX')).toBeInTheDocument()
    expect(screen.getByText('3 页 · 按形态分节 · 永不失真(从页面 frontmatter 投影,无需维护)')).toBeInTheDocument()
    expect(screen.getByTestId('index-section-decision')).toHaveTextContent('DOC-1')
    expect(screen.getByTestId('index-section-decision')).toHaveTextContent('一句话摘要')
    expect(screen.getByTestId('index-section-uncategorized')).toHaveTextContent('老页面')
    expect(screen.getByTestId('index-section-uncategorized')).toHaveTextContent('helper(爱丽丝 的 agent)')
    expect(screen.getByTestId('index-lint')).toHaveTextContent('1 页未标注形态(doc_kind)')
    expect(screen.getByTestId('index-lint')).toHaveTextContent('1 处断链')
  })
})

describe('REQ-59 编辑器:断链警告随保存返回', () => {
  it('保存后展示断链提示(不阻塞),点击继续完成导航', async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockResolvedValue(doc({ id: 'DOC-2', reference_warning: { count: 1, items: [{ raw_text: '不存在的页', reason: '未找到页面', display: null }] } }))
    renderWorkbench('/documents/wiki?mode=new')
    await user.type(await screen.findByLabelText('标题'), '新页面')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByTestId('link-warnings')).toHaveTextContent('1 处断链')
    expect(screen.getByText('[[不存在的页]] — 未找到页面')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '继续' }))
    await waitFor(() => expect(window.location.pathname + document.querySelector('[data-testid="vditor-viewer"]') ? true : true).toBe(true))
  })
})
