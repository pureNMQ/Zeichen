import { useLayoutEffect, useRef, type ComponentProps } from 'react'

import type { WysiwygMarkdownEditor } from '@/components/vditor-ir-editor'

type Props = ComponentProps<typeof WysiwygMarkdownEditor>

/** jsdom omits the browser editing engine. Keep real focus, selection ranges and input events. */
export function FakeWysiwygMarkdownEditor(props: Props) {
  const elementRef = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  latest.current = props
  const local = useRef<string | null>(null)

  useLayoutEffect(() => {
    const element = elementRef.current!
    function getRange() {
      const selection = document.getSelection()
      if (selection?.rangeCount && element.contains(selection.anchorNode)) return selection.getRangeAt(0).cloneRange()
      const range = document.createRange()
      range.selectNodeContents(element)
      range.collapse(false)
      return range
    }
    function insert(range: Range, node: Node, space: boolean) {
      element.focus()
      range.deleteContents()
      range.insertNode(node)
      range.setStartAfter(node)
      if (space) {
        const after = range.startContainer.childNodes[range.startOffset]
        if (after instanceof Text && after.data.startsWith(' ')) range.setStart(after, 1)
        else {
          const padding = document.createTextNode(' ')
          range.insertNode(padding)
          range.setStart(padding, 1)
        }
      }
      range.collapse(true)
      const selection = document.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(range)
      element.dispatchEvent(new Event('input', { bubbles: true }))
    }
    latest.current.onEditorReady?.({
      element, getRange,
      insertText: (range, value) => insert(range, document.createTextNode(value), false),
      insertLink: (range, label, href, image) => {
        const link = image ? document.createElement('img') : document.createElement('a')
        if (link instanceof HTMLImageElement) {
          link.alt = label
          link.setAttribute('src', href)
        } else {
          link.setAttribute('href', href)
          link.textContent = label
        }
        insert(range, link, true)
      },
    })
    return () => latest.current.onEditorReady?.(null)
  }, [])
  useLayoutEffect(() => {
    if (props.initialMarkdown !== local.current) elementRef.current!.textContent = props.initialMarkdown
  }, [props.initialMarkdown])

  return <div ref={elementRef} role="textbox" id={props.id} aria-label={props.ariaLabel}
    contentEditable={!props.disabled} suppressContentEditableWarning onInput={() => {
      const copy = elementRef.current!.cloneNode(true) as HTMLElement
      for (const link of copy.querySelectorAll('a, img')) {
        const label = link.textContent || link.getAttribute('alt') || ''
        link.replaceWith((link.tagName === 'IMG' ? '!' : '') + '[' + label + '](<' +
          (link.getAttribute('href') ?? link.getAttribute('src')) + '>)')
      }
      local.current = copy.textContent
      latest.current.onChange(copy.textContent)
    }} />
}
