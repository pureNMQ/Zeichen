import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/components/vditor-ir-editor', () => ({
  VditorIrEditor: ({ initialMarkdown, onChange }: { initialMarkdown: string; onChange: (markdown: string) => void }) => <textarea aria-label="Markdown 正文" autoComplete="off" data-testid="vditor-ir-editor" defaultValue={initialMarkdown} onChange={(event) => onChange(event.target.value)} />,
  VditorMarkdownViewer: ({ markdown }: { markdown: string }) => <div>{markdown}</div>,
}))
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) { super(message); this.status = status }
  }
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

import { api } from '@/lib/api'
import { CurrentProjectProvider } from '@/lib/current-project'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { DocumentWorkbenchPage } from '@/pages/documents'

const nodes = [{ id: 'parent', node_kind: 'document' as const, title: '父 Wiki', doc_type: 'wiki' as const, content: '', metadata: {}, project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', deleted_at: null, parent_id: null, directory_id: null, has_children: true }, { id: 'other', node_kind: 'document' as const, title: '另一篇 Wiki', doc_type: 'wiki' as const, content: '', metadata: {}, project_id: 'p1', created_by: 'u1', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', deleted_at: null, parent_id: null, directory_id: null, has_children: false }]
function renderWorkbench(entry = '/documents/wiki') { const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); return render(<QueryClientProvider client={client}><CurrentProjectProvider><DocumentNavigationProvider><MemoryRouter initialEntries={[entry]}><Routes><Route path="/documents/wiki" element={<DocumentWorkbenchPage module="wiki" />} /><Route path="/documents/wiki/:id" element={<DocumentWorkbenchPage module="wiki" />} /><Route path="/documents/glossary" element={<DocumentWorkbenchPage module="glossary" />} /><Route path="/documents/glossary/term/:id" element={<DocumentWorkbenchPage module="glossary" />} /><Route path="/documents/glossary/directory/:id" element={<DocumentWorkbenchPage module="glossary" routeNodeKind="directory" />} /></Routes></MemoryRouter></DocumentNavigationProvider></CurrentProjectProvider></QueryClientProvider>) }
describe('文档工作台', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); vi.mocked(api.get).mockImplementation((path: string) => { if (path === '/projects') return Promise.resolve([{ id: 'p1', name: '测试项目', created_at: '2026-08-01T00:00:00Z', my_role: 'owner' }]); if (path === '/projects/p1/documents/wiki/children?limit=100') return Promise.resolve({ items: nodes, next_cursor: null }); if (path === '/projects/p1/documents/wiki/children?parent_id=parent&limit=100') return Promise.resolve({ items: [nodes[1]], next_cursor: null }); return Promise.resolve({ items: [], next_cursor: null }) }); vi.mocked(api.post).mockImplementation((path: string, body?: unknown) => path === '/projects/p1/documents/wiki' ? Promise.resolve({ ...nodes[1], id: 'new-document', title: (body as { title: string }).title }) : Promise.resolve({})) })
  it('仅加载根节点并保留搜索占位', async () => { renderWorkbench(); const search = await screen.findByRole('textbox', { name: '搜索文档（即将支持）' }); expect(search).toBeDisabled(); expect(search).toHaveAttribute('autocomplete', 'off'); await waitFor(() => expect(api.get).toHaveBeenCalledWith('/projects/p1/documents/wiki/children?limit=100')) })
  it('在工作台中创建 Wiki', async () => { const user = userEvent.setup(); renderWorkbench('/documents/wiki?mode=new'); await user.type(await screen.findByLabelText('标题'), '新文档'); await user.click(screen.getByRole('button', { name: '保存' })); await waitFor(() => expect(api.post).toHaveBeenCalledWith('/projects/p1/documents/wiki', expect.objectContaining({ doc_type: 'wiki', title: '新文档' }))) })
  it('编辑器有未保存更改时提示用户确认切换', async () => { const user = userEvent.setup(); renderWorkbench('/documents/wiki?mode=new'); await user.type(await screen.findByLabelText('标题'), '草稿'); await user.click(screen.getByRole('button', { name: '另一篇 Wiki' })); expect(await screen.findByRole('dialog')).toHaveTextContent('保存并切换') })
})
