import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('@/components/vditor-ir-editor', () => ({
  VditorIrEditor: ({ initialMarkdown, onChange }: { initialMarkdown: string; onChange: (markdown: string) => void }) => <textarea aria-label="完整说明" autoComplete="off" defaultValue={initialMarkdown} onChange={(event) => onChange(event.target.value)} />,
  VditorMarkdownViewer: ({ markdown }: { markdown: string }) => <div>{markdown}</div>,
}))

vi.mock('@/lib/current-project', () => ({
  useCurrentProject: () => ({ currentProject: { id: 'p1', name: '测试项目' }, isLoading: false }),
  useProjectRole: () => 'owner',
}))

vi.mock('@/lib/api', () => {
  class ApiError extends Error { status = 400 }
  return { ApiError, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }
})

import { api } from '@/lib/api'
import { CodeReferencePage } from '@/pages/code-reference'

const library = { id: 'lib1', project_id: 'p1', name: 'Core', language: 'csharp', package: 'Core', version: null, created_at: '', updated_at: '', deleted_at: null }
let symbol = {
  id: 'symbol1', library_id: 'lib1', owner_symbol_id: null, kind: 'class' as const, name: 'Vector3', qualified_name: 'Core.Math.Vector3', namespace: 'Math', summary: '旧摘要', remarks: '旧说明', accessibility: 'public' as const,
  source_declaration: null, since_version: null, deprecated: false, definition: { type_parameters: [], base_type: null, interfaces: [], modifiers: [] }, members: [], signature: 'class Vector3', revision: 1, created_at: '', updated_at: '', deleted_at: null,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/code-reference/symbol1?mode=edit']}><Routes><Route path="/code-reference/:id" element={<CodeReferencePage />} /></Routes></MemoryRouter></QueryClientProvider>)
}

describe('代码 API 参考预览', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    symbol = { ...symbol, summary: '旧摘要', remarks: '旧说明', revision: 1 }
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/projects/p1/code-reference/libraries') return Promise.resolve({ items: [library] })
      if (path === '/projects/p1/code-reference/tree') return Promise.resolve({ items: [] })
      if (path === '/code-reference/symbols/symbol1') return Promise.resolve(symbol)
      return Promise.resolve({ items: [] })
    })
    vi.mocked(api.patch).mockImplementation((_path: string, body: unknown) => {
      symbol = { ...symbol, ...(body as { summary: string }), revision: 2 }
      return Promise.resolve(symbol)
    })
  })

  it('保存编辑后立即显示最新符号详情', async () => {
    const user = userEvent.setup()
    renderPage()

    const summary = await screen.findByLabelText('摘要')
    await user.clear(summary)
    await user.type(summary, '新摘要')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(screen.getByText('新摘要')).toBeInTheDocument())
  })
})
