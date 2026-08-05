import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const vditorMock = vi.hoisted(() => {
  const instance = {
    destroy: vi.fn(),
    disabled: vi.fn(),
    enable: vi.fn(),
    updateToolbarConfig: vi.fn(),
    getValue: vi.fn(() => ''),
    setValue: vi.fn(),
  }
  const constructor = vi.fn(function () { return instance })
  const preview = vi.fn(() => Promise.resolve())
  Object.assign(constructor, { preview })
  return { constructor, instance, preview }
})

vi.mock('vditor', () => ({ default: vditorMock.constructor }))
vi.mock('vditor/dist/index.css', () => ({}))

import { VditorIrEditor, VditorMarkdownViewer } from '@/components/vditor-ir-editor'

describe('VditorIrEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates one IR editor with the approved basic toolbar and disabled local cache', async () => {
    const onChange = vi.fn()
    const onReady = vi.fn()

    render(<VditorIrEditor initialMarkdown="# Title" onChange={onChange} onReady={onReady} />)

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
      mode: 'ir',
      value: '# Title',
      placeholder: '输入 / 添加内容，或直接开始写作',
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
    const { unmount } = render(<VditorIrEditor initialMarkdown="" onChange={vi.fn()} />)

    await waitFor(() => expect(vditorMock.constructor).toHaveBeenCalledTimes(1))
    const [, options] = vditorMock.constructor.mock.calls[0]! as unknown as [HTMLElement, { after: () => void }]
    act(() => options.after())
    unmount()

    expect(vditorMock.instance.destroy).toHaveBeenCalledTimes(1)
  })

  it('does not call Vditor instance methods before asynchronous initialization completes', async () => {
    const { unmount } = render(<VditorIrEditor initialMarkdown="" onChange={vi.fn()} />)

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
    const { container } = render(<VditorIrEditor initialMarkdown="" onChange={vi.fn()} />)

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
  it('renders Markdown through Vditor preview with the pinned CDN', async () => {
    render(<VditorMarkdownViewer markdown="**read me**" ariaLabel="正文预览" />)

    await waitFor(() => expect(vditorMock.preview).toHaveBeenCalledWith(
      expect.any(HTMLDivElement),
      '**read me**',
      expect.objectContaining({ cdn: 'https://cdn.jsdelivr.net/npm/vditor@3.11.2' }),
    ))
  })
})
