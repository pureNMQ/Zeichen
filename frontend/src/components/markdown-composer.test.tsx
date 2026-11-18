import { useState } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MarkdownComposer, type CompletionCandidate, type CompletionLookup } from '@/components/markdown-composer'
import { NotificationProvider } from '@/components/ui/notification'

vi.mock('@/components/vditor-ir-editor', async () => ({
  WysiwygMarkdownEditor: (await import('@/test/fake-wysiwyg-editor')).FakeWysiwygMarkdownEditor,
}))

function selectText(editor: HTMLElement, start: number, end: number) {
  const range = document.createRange()
  range.setStart(editor.firstChild!, start)
  range.setEnd(editor.firstChild!, end)
  const selection = window.getSelection()!
  selection.removeAllRanges()
  selection.addRange(range)
}

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
    editor: screen.getByRole<HTMLElement>('textbox', { name: 'Markdown 正文' }),
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
    expect(editor).toHaveTextContent('请问 @小青 请确认')
    expect(editor.querySelector('a')).toHaveTextContent(/^@小青$/)
    expect(editor.querySelector('a')).toHaveAttribute('href', agent.href)
  })

  it('filters references by name and replaces only the selected text', async () => {
    const lookup = vi.fn<CompletionLookup>(async (mode, query) => mode === 'reference' && query === '发布 文档' ? [wiki] : [])
    const { user, editor } = setup(lookup, '先看 这里 再回复')
    await user.click(editor)
    selectText(editor, 3, 5)
    await user.keyboard('{Alt>}k{/Alt}')
    const search = screen.getByRole('combobox', { name: '查找引用' })
    expect(search).toHaveFocus()
    await user.type(search, '发布 文档')
    expect(await screen.findByRole('option', { name: '发布 [手册] Wiki · DOC-1' })).toBeVisible()
    await user.keyboard('{Enter}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveTextContent('先看 发布 [手册] 再回复')
    expect(editor.querySelector('a')).toHaveAttribute('href', wiki.href)
    await user.keyboard('然后')
    expect(editor).toHaveTextContent('然后再回复')
  })

  it('cancels selection without changing the draft and inserts an image using its stable file URL', async () => {
    const lookup = vi.fn<CompletionLookup>(async (mode) => mode === 'image' ? [image] : [])
    const { user, editor } = setup(lookup, '开头')
    await user.click(editor)
    await user.keyboard('{Alt>}k{/Alt}{Escape}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveTextContent('开头')
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()

    await user.keyboard(' {Alt>}{Shift>}K{/Shift}{/Alt}')
    expect(screen.getByRole('combobox', { name: '查找图片' })).toHaveFocus()
    expect(await screen.findByRole('option', { name: '封面 文件' })).toBeVisible()
    await user.keyboard('{Enter}')
    expect(editor).toHaveFocus()
    expect(editor.querySelector('img')).toHaveAttribute('src', image.href)
    expect(editor.querySelector('img')).toHaveAttribute('alt', '封面')
  })

  it('inserts an ordinary file as a link and wraps the keyboard selection', async () => {
    const lookup = vi.fn<CompletionLookup>(async (mode) => mode === 'reference' ? [wiki, file] : [])
    const { user, editor } = setup(lookup)
    await user.click(editor)
    await user.keyboard('{Alt>}k{/Alt}')
    expect(await screen.findByRole('option', { name: '安装说明.pdf 文件' })).toHaveAttribute('aria-selected', 'false')
    await user.keyboard('{ArrowUp}{Enter}')
    expect(editor).toHaveFocus()
    expect(editor.querySelector('a')).toHaveAttribute('href', file.href)
  })

  it('looks up references inline, replaces the whole trigger and continues outside the link on Tab', async () => {
    const lookup = vi.fn<CompletionLookup>(async () => [wiki])
    const { user, editor } = setup(lookup)
    await user.click(editor)
    await user.keyboard('请看[[[[发布')
    expect(await screen.findByRole('option', { name: '发布 [手册] Wiki · DOC-1' })).toBeVisible()
    expect(lookup).toHaveBeenLastCalledWith('reference', '发布', expect.any(AbortSignal))
    await user.keyboard('{Tab}继续')
    expect(editor.querySelector('a')).toHaveAttribute('href', wiki.href)
    expect(editor).toHaveTextContent('请看发布 [手册] 继续')
    expect(editor.querySelector('a')!.textContent).toBe('发布 [手册]')
  })

  it('inserts a mention inside Chinese prose without consuming the following characters', async () => {
    const { user, editor } = setup(async () => [member], '通知后继续')
    await user.click(editor)
    selectText(editor, 2, 2)
    await user.keyboard('@小')
    await user.click(await screen.findByRole('option', { name: '小青 成员' }))
    expect(editor).toHaveTextContent('通知@小青 后继续')
    expect(editor.querySelector('a')).toHaveAttribute('href', member.href)
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
    expect(editor).toHaveTextContent('dev@example.com @小')
    fireEvent.compositionEnd(editor)
    await user.keyboard('{Escape}')
    expect(editor).toHaveFocus()
    expect(editor).toHaveTextContent('dev@example.com @小')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('discards a picker when a new draft replaces the body and immediately allows inline lookup there', async () => {
    const lookup = vi.fn<CompletionLookup>(async () => [member])
    const onChange = vi.fn()
    const view = (value: string) => <MarkdownComposer value={value} onChange={onChange} lookup={lookup} />
    const { rerender } = render(view('第一份'))
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '插入引用' }))
    expect(screen.getByRole('combobox', { name: '查找引用' })).toHaveFocus()
    rerender(view('第二份'))
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    const editor = screen.getByRole('textbox', { name: 'Markdown 正文' })
    await user.type(editor, '@小')
    expect(await screen.findByRole('option', { name: '小青 成员' })).toBeVisible()
    expect(lookup).toHaveBeenLastCalledWith('people', '小', expect.any(AbortSignal))
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
    expect(editor).toHaveTextContent('保留草稿')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('option', { name: '发布 [手册] Wiki · DOC-1' })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(editor).toHaveTextContent('保留草稿')
  })
})
