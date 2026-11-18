import type { CompletionMode } from './markdown-composer'

export type InlineCompletion = {
  mode: CompletionMode
  query: string
  replace: Range
  caret: Range
}

export function sameRange(a: Range, b: Range) {
  return a.startContainer === b.startContainer && a.startOffset === b.startOffset &&
    a.endContainer === b.endContainer && a.endOffset === b.endOffset
}

/** Only adjacent text is a token: a formatted link, code span or line break ends it. */
export function inlineCompletion(element: HTMLElement): InlineCompletion | null {
  const selection = element.ownerDocument.getSelection()
  if (!selection?.isCollapsed || !selection.rangeCount) return null
  const caret = selection.getRangeAt(0).cloneRange()
  const node = caret.startContainer
  if (!element.contains(node) || !(node instanceof Text)) return null
  const literal = node.parentElement?.closest('a, code, pre, [data-type="math-inline"], [contenteditable="false"]')
  if (literal && literal !== element && element.contains(literal)) return null

  const nodes = [node]
  for (let prev = node.previousSibling; prev instanceof Text; prev = prev.previousSibling) nodes.unshift(prev)
  for (let next = node.nextSibling; next instanceof Text; next = next.nextSibling) nodes.push(next)
  const text = nodes.map((part) => part.data).join('')
  const cursor = nodes.slice(0, nodes.indexOf(node)).reduce((n, part) => n + part.length, caret.startOffset)
  const before = text.slice(0, cursor)
  const reference = /(!?\[\[)([^[\]\n]{0,200})$/u.exec(before)
  const person = /(?:^|[^\p{Script=Latin}\p{N}_.+@-])@([^\s@()[\]{}<>\\,!?;:，。！？、；：]{0,200})$/u.exec(before)
  if (!reference && !person) return null
  const mode = reference ? (reference[1] === '![[' ? 'image' : 'reference') : 'people'
  const query = reference ? reference[2] : person![1]
  const start = cursor - query.length - (reference ? reference[1].length : 1)
  // Following prose can be adjacent to a mention in Chinese. Only consume the typed prefix.
  const end = cursor + (reference && text.startsWith(']]', cursor) ? 2 : 0)
  const replace = caret.cloneRange()
  let offset = 0
  for (const part of nodes) {
    if (start >= offset && start <= offset + part.length) replace.setStart(part, start - offset)
    if (end >= offset && end <= offset + part.length) replace.setEnd(part, end - offset)
    offset += part.length
  }
  return { mode, query, replace, caret }
}

/** Browsers can return an empty rect for a collapsed caret on an empty line. */
export function caretRect(caret: Range): DOMRect {
  const range = caret.cloneRange()
  range.collapse(false)
  const rect = range.getBoundingClientRect?.()
  if (rect?.height) return rect
  const node = range.startContainer
  if (node instanceof Text && node.length && range.getBoundingClientRect) {
    const index = range.startOffset
    range.setStart(node, Math.max(0, index - 1))
    range.setEnd(node, index || 1)
    const glyph = range.getBoundingClientRect()
    if (glyph.height) return new DOMRect(index ? glyph.right : glyph.left, glyph.top, 0, glyph.height)
  }
  const block = node instanceof Element ? node : node.parentElement
  const box = block?.getBoundingClientRect()
  return new DOMRect(box?.left ?? 0, box?.top ?? 0, 0, Number.parseFloat(block ? getComputedStyle(block).lineHeight : '') || 20)
}
