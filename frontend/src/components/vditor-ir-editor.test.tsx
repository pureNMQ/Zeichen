import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const vditorMock = vi.hoisted(() => {
  const instance = {
    destroy: vi.fn(),
    disabled: vi.fn(),
    enable: vi.fn(),
    setTheme: vi.fn(),
    updateToolbarConfig: vi.fn(),
    getValue: vi.fn(() => ''),
    setValue: vi.fn(),
    vditor: { wysiwyg: { composingLock: false } },
  }
  const constructor = vi.fn(function () { return instance })
  const preview = vi.fn((_target: HTMLElement, _markdown: string) => Promise.resolve())
  Object.assign(constructor, { preview })
  return { constructor, instance, preview }
})

vi.mock('vditor', () => ({ default: vditorMock.constructor }))
vi.mock('vditor/dist/index.css', () => ({}))

import { WysiwygMarkdownEditor, VditorMarkdownViewer } from '@/components/vditor-ir-editor'

describe('WysiwygMarkdownEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates a WYSIWYG editor with local resources, a selection toolbar and no local cache', async () => {
    const onChange = vi.fn()
    const onReady = vi.fn()

    render(<WysiwygMarkdownEditor initialMarkdown="# Title" onChange={onChange} onReady={onReady} />)

    await waitFor(() => expect(vditorMock.constructor).toHaveBeenCalledTimes(1))
    const [, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, {
      mode: string
      value: string
      placeholder: string
      toolbar: string[]
      toolbarConfig: { hide: boolean; pin: boolean }
      cache: { enable: boolean }
      input: (markdown: string) => void
      after: () => void
    }]
    expect(options).toMatchObject({
      mode: 'wysiwyg',
      cdn: '/vendor/vditor',
      value: '# Title',
      placeholder: '输入正文',
      cache: { enable: false },
      toolbar: ['headings', 'bold', 'italic', 'strike', 'quote', 'line', 'list', 'ordered-list', 'link', 'inline-code', 'code', 'undo', 'redo'],
      toolbarConfig: { hide: true, pin: false },
    })

    act(() => options.input('updated markdown'))
    expect(onChange).toHaveBeenCalledWith('updated markdown')

    act(() => options.after())
    expect(onReady).toHaveBeenCalledWith(vditorMock.instance)
  })

  it('destroys the Vditor instance when unmounted', async () => {
    const { unmount } = render(<WysiwygMarkdownEditor initialMarkdown="" onChange={vi.fn()} />)

    await waitFor(() => expect(vditorMock.constructor).toHaveBeenCalledTimes(1))
    const [, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, { after: () => void }]
    act(() => options.after())
    unmount()

    expect(vditorMock.instance.destroy).toHaveBeenCalledTimes(1)
  })

  it('reports native edits immediately, preserves the caret on parent echoes and applies external resets', async () => {
    const onChange = vi.fn()
    const onEditorReady = vi.fn()
    const { rerender, unmount } = render(<WysiwygMarkdownEditor initialMarkdown="已有正文"
      onChange={onChange} onEditorReady={onEditorReady} ariaLabel="任务正文" />)
    const [mount, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, { after: () => void }]
    mount.innerHTML = '<div class="vditor-wysiwyg"><pre class="vditor-reset" contenteditable="true"></pre></div>'
    vditorMock.instance.getValue.mockReturnValue('已有正文\n')
    act(() => options.after())
    const field = screen.getByRole('textbox', { name: '任务正文' })
    fireEvent.focusOut(field)
    expect(onChange).not.toHaveBeenCalled()

    vditorMock.instance.getValue.mockReturnValue('最新正文\n')
    fireEvent.input(field)
    expect(onChange).toHaveBeenLastCalledWith('最新正文\n')
    rerender(<WysiwygMarkdownEditor initialMarkdown={'最新正文\n'} onChange={onChange} onEditorReady={onEditorReady} />)
    expect(vditorMock.instance.setValue).not.toHaveBeenCalled()
    rerender(<WysiwygMarkdownEditor initialMarkdown="" onChange={onChange} onEditorReady={onEditorReady} />)
    expect(vditorMock.instance.setValue).toHaveBeenCalledWith('', true)
    unmount()
    expect(onEditorReady).toHaveBeenLastCalledWith(null)
  })

  it('uses the authenticated image preview without replacing the Markdown image destination', () => {
    const href = '/projects/11111111-1111-4111-8111-111111111111/files/22222222-2222-4222-8222-222222222222'
    render(<WysiwygMarkdownEditor initialMarkdown="" onChange={vi.fn()} />)
    const [mount, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, { after: () => void }]
    mount.innerHTML = `<div class="vditor-wysiwyg"><pre class="vditor-reset" contenteditable="true"><img alt="示例图" src="${href}"></pre></div>`
    act(() => options.after())
    const img = screen.getByRole('img', { name: '示例图' })
    expect(img).toHaveAttribute('src', href)
    expect(img).toHaveAttribute('srcset', `/api/v2${href}/content?inline=true`)
  })

  it('does not call Vditor instance methods before asynchronous initialization completes', async () => {
    const { unmount } = render(<WysiwygMarkdownEditor initialMarkdown="" onChange={vi.fn()} />)

    await waitFor(() => expect(vditorMock.constructor).toHaveBeenCalledTimes(1))
    const [, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, { after: () => void }]

    expect(vditorMock.instance.enable).not.toHaveBeenCalled()
    expect(vditorMock.instance.disabled).not.toHaveBeenCalled()

    unmount()
    expect(vditorMock.instance.destroy).not.toHaveBeenCalled()

    act(() => options.after())
    expect(vditorMock.instance.destroy).toHaveBeenCalledTimes(1)
  })

  it('reveals formatting tools only for a text selection inside the document canvas', async () => {
    const { container } = render(<WysiwygMarkdownEditor initialMarkdown="" onChange={vi.fn()} />)

    await waitFor(() => expect(vditorMock.constructor).toHaveBeenCalledTimes(1))
    const [, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, { after: () => void }]
    const host = container.querySelector('[aria-busy]')!
    host.innerHTML = '<div class="vditor-toolbar"></div><pre class="vditor-reset" contenteditable="true">format this text</pre>'
    const text = host.querySelector('pre')!.firstChild!
    const range = document.createRange()
    range.selectNodeContents(text)
    Object.assign(range, { getBoundingClientRect: () => ({ left: 20, top: 20, width: 80 }) })
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)

    act(() => options.after())
    act(() => document.dispatchEvent(new Event('selectionchange')))

    expect(vditorMock.instance.updateToolbarConfig).toHaveBeenCalledWith({ hide: false, pin: false })
    selection.removeAllRanges()
  })
})

describe('VditorMarkdownViewer', () => {
  it('renders Markdown through Vditor preview with packaged local assets', async () => {
    render(<VditorMarkdownViewer markdown="**read me**" ariaLabel="正文预览" />)

    await waitFor(() => expect(vditorMock.preview).toHaveBeenCalledWith(
      expect.any(HTMLDivElement),
      '**read me**',
      expect.objectContaining({ cdn: '/vendor/vditor' }),
    ))
  })

  it('shows authenticated previews for canonical file images and falls back to a stable link on error', async () => {
    const href = '/projects/11111111-1111-4111-8111-111111111111/files/22222222-2222-4222-8222-222222222222'
    vditorMock.preview.mockImplementationOnce(async (target) => {
      target.innerHTML = `<img src="${href}" alt="预览图片"><img src="https://example.invalid/image.png" alt="外部图片">`
    })
    render(<VditorMarkdownViewer markdown={`![预览图片](<${href}>)`} />)

    const image = await screen.findByRole('img', { name: '预览图片' })
    expect(image).toHaveAttribute('src', `/api/v2${href}/content?inline=true`)
    expect(screen.getByRole('img', { name: '外部图片' })).toHaveAttribute('src', 'https://example.invalid/image.png')
    fireEvent.error(image)
    expect(screen.getByRole('link', { name: '预览图片' })).toHaveAttribute('href', href)
  })
})
