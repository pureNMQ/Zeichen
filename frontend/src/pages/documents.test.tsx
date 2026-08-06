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
              <Route path="/documents/api" element={<DocumentWorkbenchPage module="api" />} />
              <Route path="/documents/api/definition/:id" element={<DocumentWorkbenchPage module="api" routeNodeKind="document" />} />
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
      if (path === '/projects/p1/libraries/code-tree') return Promise.resolve({ items: [{
        node_kind: 'package', id: 'package:Core', title: 'Core', language: 'C#', children: [{
          node_kind: 'namespace', id: 'namespace:Core.Math', title: 'Core.Math', children: [{
            node_kind: 'symbol', id: 'vector-symbol', title: 'Vector3', symbol_kind: 'struct', document: { ...rootNodes[1], id: 'vector-doc', doc_type: 'api', library_symbol: { canonical_signature: 'struct Vector3' } }, children: [{
              node_kind: 'member_group', id: 'fields', title: '字段', children: [{
                node_kind: 'symbol', id: 'x-symbol', title: 'x', symbol_kind: 'field', document: { ...rootNodes[1], id: 'x-doc', doc_type: 'api', library_symbol: { canonical_signature: 'float x' } }, children: [],
              }],
            }],
          }],
        }],
      }] })
      if (path === '/projects/p1/libraries/symbols') return Promise.resolve({ items: [{
        id: 'vector-symbol', document_id: 'vector-doc', language: 'C#', package: 'Core', namespace: 'Core.Math', symbol: 'Vector3', kind: 'struct', canonical_signature: 'struct Vector3',
      }] })
      if (path === '/projects/p1/documents/api/children?limit=100') return Promise.resolve({ items: [], next_cursor: null })
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
      if (path === '/projects/p1/documents/api') {
        return Promise.resolve({
          ...rootNodes[1], id: 'library-symbol', doc_type: 'api', title: (body as { title: string }).title,
          library_symbol: (body as { library_symbol: unknown }).library_symbol,
        })
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

  it('新建主按钮提供根 Wiki 与子 Wiki 两种创建位置', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/wiki/child')

    await user.click(await screen.findByRole('button', { name: '新建' }))

    expect(await screen.findByRole('menuitem', { name: '新建 Wiki' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '新建子 Wiki' })).toBeInTheDocument()
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

  it('新建程序库 API 使用符号表单提交，而不是 endpoint metadata', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/api?mode=new')

    await user.type(await screen.findByLabelText('标题'), 'Vector3.Normalize')
    await user.type(screen.getByLabelText('包或模块'), 'Core.Math')
    await user.clear(screen.getByLabelText('符号名'))
    await user.type(screen.getByLabelText('符号名'), 'Normalize')
    await user.type(screen.getByLabelText('原始代码签名'), 'Vector3 Normalize()')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/documents/api', expect.objectContaining({
      title: 'Normalize',
      doc_type: 'api',
      library_symbol: expect.objectContaining({ language: 'C#', package: 'Core.Math', symbol: 'Normalize', canonical_signature: 'Vector3 Normalize()' }),
    })))
  })

  it('新建代码成员时继承所属结构的位置，不显示也不提交语言、包和命名空间', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/api?mode=new&kind=method&owner_id=vector-symbol')

    await user.type(await screen.findByLabelText('符号名'), 'Normalize')
    expect(screen.queryByLabelText('语言')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('包或模块')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('命名空间')).not.toBeInTheDocument()
    expect(screen.getByText('语言、包和命名空间由所属代码结构继承。')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/documents/api', expect.objectContaining({
      library_symbol: expect.objectContaining({ owner_symbol_id: 'vector-symbol', kind: 'method', symbol: 'Normalize' }),
    })))
    const request = vi.mocked(api.post).mock.calls.find(([path]) => path === '/projects/p1/documents/api')?.[1] as { library_symbol: Record<string, unknown> }
    expect(request.library_symbol).not.toHaveProperty('language')
    expect(request.library_symbol).not.toHaveProperty('package')
    expect(request.library_symbol).not.toHaveProperty('namespace')
  })

  it('新建构造函数自动使用所属类型名称，且不提交返回值', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/api?mode=new&kind=constructor&owner_id=vector-symbol')

    expect(await screen.findByRole('heading', { name: 'Vector3' })).toBeInTheDocument()
    expect(screen.queryByLabelText('标题')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/documents/api', expect.objectContaining({
      title: 'Vector3.ctor',
      library_symbol: expect.objectContaining({ owner_symbol_id: 'vector-symbol', kind: 'constructor', symbol: 'Vector3' }),
    })))
    const request = vi.mocked(api.post).mock.calls.find(([path]) => path === '/projects/p1/documents/api')?.[1] as { library_symbol: Record<string, unknown> }
    expect(request.library_symbol).not.toHaveProperty('return_type')
    expect(request.library_symbol).not.toHaveProperty('return_description')
  })

  it('字段提供独立的类型输入，并保存为结构化定义', async () => {
    const user = userEvent.setup()
    renderWorkbench('/documents/api?mode=new&kind=field&owner_id=vector-symbol')

    await user.type(await screen.findByLabelText('符号名'), 'x')
    await user.type(screen.getByLabelText('类型'), 'float')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/documents/api', expect.objectContaining({
      library_symbol: expect.objectContaining({ kind: 'field', symbol: 'x', return_type: 'float' }),
    })))
  })

  it('程序库 API 以代码树展示程序库、命名空间和成员', async () => {
    renderWorkbench('/documents/api')

    expect(await screen.findByText('Core')).toBeInTheDocument()
    expect(screen.getByText('Core.Math')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Vector3/ })).not.toHaveLength(0)
    expect(screen.getByText('x')).toBeInTheDocument()
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
