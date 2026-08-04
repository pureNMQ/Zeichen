import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const vditorMock = vi.hoisted(() => {
  const instance = {
    destroy: vi.fn(),
    disabled: vi.fn(),
    enable: vi.fn(),
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
      toolbar: string[]
      cache: { enable: boolean }
      input: (markdown: string) => void
      after: () => void
    }]
    expect(options).toMatchObject({
      mode: 'ir',
      value: '# Title',
      cache: { enable: false },
      toolbar: ['headings', 'bold', 'italic', 'strike', 'quote', 'line', 'list', 'ordered-list', 'link', 'inline-code', 'code', 'undo', 'redo'],
    })

    act(() => options.input('updated markdown'))
    expect(onChange).toHaveBeenCalledWith('updated markdown')

    act(() => options.after())
    expect(onReady).toHaveBeenCalledWith(vditorMock.instance)
  })

  it('destroys the Vditor instance when unmounted', async () => {
    const { unmount } = render(<VditorIrEditor initialMarkdown="" onChange={vi.fn()} />)

    await waitFor(() => expect(vditorMock.constructor).toHaveBeenCalledTimes(1))
    unmount()

    expect(vditorMock.instance.destroy).toHaveBeenCalledTimes(1)
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
