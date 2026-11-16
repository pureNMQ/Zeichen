import { useState } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MarkdownComposer, type CompletionCandidate, type CompletionLookup } from '@/components/markdown-composer'
import { NotificationProvider } from '@/components/ui/notification'

const project = '/projects/123e4567-e89b-12d3-a456-426614174000'
const member: CompletionCandidate = { id: 'member', label: '小青', kind: 'member', href: `${project}/people/member` }
const agent: CompletionCandidate = { id: 'agent', label: '小青', kind: 'agent', href: `${project}/people/agent` }
const wiki: CompletionCandidate = { id: 'DOC-1', label: '发布 [手册]', kind: 'wiki', href: `${project}/wiki/DOC-1`, detail: 'DOC-1' }
const file: CompletionCandidate = { id: 'file', label: '安装说明.pdf', kind: 'file', href: `${project}/files/file` }
const image: CompletionCandidate = { id: 'image', label: '封面', kind: 'file', href: `${project}/files/image`, thumbnailUrl: '/preview/image' }

function setup(lookup: CompletionLookup, initialValue = '') {
  function Draft() {
    const [value, setValue] = useState(initialValue)
    return <MarkdownComposer value={value} onChange={setValue} lookup={lookup} />
  }
  render(<NotificationProvider><Draft /></NotificationProvider>)
  return {
    user: userEvent.setup(),
    editor: screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Markdown 正文' }),
  }
}

describe('MarkdownComposer', () => {
  it('completes a same-name Agent by keyboard and resumes typing in the draft', async () => {
    const lookup = vi.fn(async () => [member, agent])
    const { user, editor } = setup(lookup)
    await user.type(editor, '请问 @小')
    expect(await screen.findByRole('option', { name: '小青 成员' })).toHaveAttribute('aria-selected', 'true')
    expect(lookup).toHaveBeenLastCalledWith('people', '小', expect.any(AbortSignal))

    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: '小青 Agent' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Enter}请确认')
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue(`请问 [@小青](<${agent.href}>) 请确认`)
  })

  it('filters references by name and replaces only the selected text', async () => {
    const lookup = vi.fn<CompletionLookup>(async (mode, query) => mode === 'reference' && query === '发布 文档' ? [wiki] : [])
    const { user, editor } = setup(lookup, '先看 这里 再回复')
    await user.click(editor)
    editor.setSelectionRange(3, 5)
    await user.keyboard('{Alt>}k{/Alt}')
    const search = screen.getByRole('combobox', { name: '查找引用' })
    expect(search).toHaveFocus()
    await user.type(search, '发布 文档')
    expect(await screen.findByRole('option', { name: '发布 [手册] Wiki · DOC-1' })).toBeVisible()
    await user.keyboard('{Enter}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue(`先看 [发布 \\[手册\\]](<${wiki.href}>) 再回复`)
    expect(editor.selectionStart).toBe(editor.value.indexOf('再回复'))
  })

  it('cancels selection without changing the draft and inserts an image using its stable file URL', async () => {
    const lookup = vi.fn<CompletionLookup>(async (mode) => mode === 'image' ? [image] : [])
    const { user, editor } = setup(lookup, '开头')
    await user.click(editor)
    await user.keyboard('{Alt>}k{/Alt}{Escape}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue('开头')
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()

    await user.keyboard(' {Alt>}{Shift>}K{/Shift}{/Alt}')
    expect(screen.getByRole('combobox', { name: '查找图片' })).toHaveFocus()
    expect(await screen.findByRole('option', { name: '封面 文件' })).toBeVisible()
    await user.keyboard('{Enter}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue(`开头 ![封面](<${image.href}>) `)
    expect(editor.value).not.toContain('/preview/image')
  })

  it('inserts an ordinary file as a link and wraps the keyboard selection', async () => {
    const lookup = vi.fn<CompletionLookup>(async (mode) => mode === 'reference' ? [wiki, file] : [])
    const { user, editor } = setup(lookup)
    await user.click(editor)
    await user.keyboard('{Alt>}k{/Alt}')
    expect(await screen.findByRole('option', { name: '安装说明.pdf 文件' })).toHaveAttribute('aria-selected', 'false')
    await user.keyboard('{ArrowUp}{Enter}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue(`[安装说明.pdf](<${file.href}>) `)
  })

  it('ignores a late response when the query has already changed', async () => {
    let resolveOld: (items: CompletionCandidate[]) => void = () => undefined
    const pendingOld = new Promise<CompletionCandidate[]>((resolve) => { resolveOld = resolve })
    const lookup = vi.fn<CompletionLookup>(async (_mode, query) => {
      if (query === 'a') return pendingOld
      return query === 'ab' ? [agent] : []
    })
    const { user, editor } = setup(lookup)
    await user.type(editor, '@a')
    await waitFor(() => expect(lookup).toHaveBeenLastCalledWith('people', 'a', expect.any(AbortSignal)))
    const oldSignal = lookup.mock.calls.at(-1)?.[2]
    await user.keyboard('b')
    expect(await screen.findByRole('option', { name: '小青 Agent' })).toBeVisible()
    expect(oldSignal?.aborted).toBe(true)
    await act(async () => resolveOld([member]))
    expect(screen.queryByRole('option', { name: '小青 成员' })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: '小青 Agent' })).toBeVisible()
  })

  it('does not select during Chinese IME composition or offer mentions in email addresses', async () => {
    const lookup = vi.fn<CompletionLookup>(async () => [member])
    const { user, editor } = setup(lookup)
    await user.type(editor, 'dev@example.com @小')
    expect(await screen.findByRole('option', { name: '小青 成员' })).toBeVisible()
    expect(lookup.mock.calls.every((args) => args[1] !== 'example.com')).toBe(true)
    fireEvent.compositionStart(editor)
    fireEvent.keyDown(editor, { key: 'Enter', isComposing: true })
    expect(editor).toHaveValue('dev@example.com @小')
    fireEvent.compositionEnd(editor)
    await user.keyboard('{Escape}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveValue('dev@example.com @小')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('uses a dismissible error notification and retries without clearing the draft', async () => {
    const lookup = vi.fn<CompletionLookup>()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue([wiki])
    const { user, editor } = setup(lookup, '保留草稿')
    await user.click(editor)
    await user.keyboard('{Alt>}k{/Alt}')
    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载候选项，请重试。')
    expect(screen.getByRole('button', { name: '关闭提示' })).toBeVisible()
    expect(editor).toHaveValue('保留草稿')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('option', { name: '发布 [手册] Wiki · DOC-1' })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(editor).toHaveValue('保留草稿')
  })
})
