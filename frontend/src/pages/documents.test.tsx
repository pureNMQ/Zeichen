import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/components/vditor-ir-editor', () => ({
  VditorIrEditor: ({ initialMarkdown, onChange }: { initialMarkdown: string; onChange: (markdown: string) => void }) => (
    <textarea
      aria-label="Markdown 正文"
      autoComplete="off"
      data-testid="vditor-ir-editor"
      defaultValue={initialMarkdown}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
  VditorMarkdownViewer: ({ markdown }: { markdown: string }) => <div data-testid="vditor-markdown-viewer">{markdown}</div>,
}))

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
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  }
})

import { api } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { DocumentWorkbenchPage } from '@/pages/documents'

let role: 'owner' | 'viewer' = 'owner'
const rootNodes = [
  {
    id: 'parent', node_kind: 'document', title: '父 Wiki', doc_type: 'wiki', content: '', metadata: {},
    project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    deleted_at: null, parent_id: null, directory_id: null, has_children: true,
  },
  {
    id: 'other', node_kind: 'document', title: '另一篇 Wiki', doc_type: 'wiki', content: '', metadata: {},
    project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    deleted_at: null, parent_id: null, directory_id: null, has_children: false,
  },
]
let treeNodes = rootNodes
let createdNode: (typeof rootNodes)[number] | null = null

function renderWorkbench(initialEntry = '/documents/wiki') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CurrentProjectProvider>
        <DocumentNavigationProvider>
          <MemoryRouter initialEntries={[initialEntry]}>
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

describe('文档工作台', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    role = 'owner'
    treeNodes = rootNodes
    createdNode = null
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects') {
        return Promise.resolve([{ id: 'p1', name: '测试项目', created_at: '2026-08-01T00:00:00Z', my_role: role }])
      }
      if (path === '/projects/p1/documents/wiki/children?limit=100') return Promise.resolve({ items: treeNodes, next_cursor: null })
      if (path === '/projects/p1/documents/wiki/children?parent_id=parent&limit=100') return Promise.resolve({ items: [rootNodes[1]], next_cursor: null })
      if (path === '/projects/p1/documents/wiki/ancestors/document/child') return Promise.resolve({ items: [rootNodes[0], { ...rootNodes[1], id: 'child', parent_id: 'parent' }] })
      if (path === '/documents/wiki/child') return Promise.resolve({ ...rootNodes[1], id: 'child', parent_id: 'parent' })
      if (path === '/documents/wiki/other') return Promise.resolve(rootNodes[1])
      if (path === '/documents/wiki/other/references') return Promise.resolve({ count: 0, items: [] })
      if (path === '/documents/wiki/child/references') return Promise.resolve({ count: 0, items: [] })
      if (path === '/documents/wiki/new-document' && createdNode) return Promise.resolve(createdNode)
      if (path === '/documents/wiki/new-document/references') return Promise.resolve({ count: 0, items: [] })
      return Promise.resolve({ items: [], next_cursor: null })
    })
    vi.mocked(api.post).mockImplementation((path: string, body?: unknown) => {
      if (path === '/projects/p1/documents/wiki') {
        createdNode = { ...rootNodes[1], id: 'new-document', title: (body as { title: string }).title }
        treeNodes = [...treeNodes, createdNode]
        return Promise.resolve(createdNode)
      }
      return Promise.resolve({})
    })
  })

  it('只加载根节点，并显示不可用的搜索占位', async () => {
    renderWorkbench()

    const search = await screen.findByRole('textbox', { name: '搜索文档（即将支持）' })
    expect(search).toBeDisabled()
    expect(search).toHaveAttribute('autocomplete', 'off')
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/projects/p1/documents/wiki/children?limit=100'))
    expect(api.get).not.toHaveBeenCalledWith('/projects/p1/documents/wiki/children?parent_id=parent&limit=100')
  })

  it('打开深链接时加载祖先路径并展开对应父节点', async () => {
    renderWorkbench('/documents/wiki/child')

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/projects/p1/documents/wiki/ancestors/document/child'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/projects/p1/documents/wiki/children?parent_id=parent&limit=100'))
  })

  it('viewer 可以浏览但看不到创建和整理操作', async () => {
    role = 'viewer'
    renderWorkbench()

    await screen.findByText('父 Wiki')
    expect(screen.queryByRole('button', { name: /新建/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重命名' })).not.toBeInTheDocument()
  })

  it('新建在右侧编辑器内完成，而不是弹出编辑对话框', async () => {
    renderWorkbench('/documents/wiki?mode=new')

    expect(await screen.findByLabelText('标题')).toHaveAttribute('id', 'document-title')
    expect(screen.getByTestId('vditor-ir-editor')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('新建页使用阅读优先的文档画布，而不是表单式编辑框', async () => {
    renderWorkbench('/documents/wiki?mode=new')

    expect(await screen.findByTestId('document-writing-canvas')).toBeInTheDocument()
    expect(screen.getByText('Wiki / 新建文档')).toBeInTheDocument()
    expect(screen.queryByText('尚未创建 · Markdown 文档')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '返回' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存' })).toBeInTheDocument()
  })

  it('保存新建 Wiki 后会刷新左侧文件树', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/wiki?mode=new')

    await user.type(await screen.findByLabelText('标题'), '新文档')
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByRole('button', { name: '新文档' })).toBeInTheDocument()
  })

  it('编辑器有未保存变更时，切换树节点会显示三选一保护', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/wiki?mode=new')

    await user.type(await screen.findByLabelText('标题'), '草稿')
    await user.click(screen.getByRole('button', { name: '另一篇 Wiki' }))

    expect(await screen.findByRole('dialog')).toHaveTextContent('保存并切换')
    expect(screen.getByRole('dialog')).toHaveTextContent('放弃更改并切换')
    expect(screen.getByRole('dialog')).toHaveTextContent('留在当前文档')
  })
})
