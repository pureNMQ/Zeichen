import { useEffect, useRef, useState } from 'react'
import Vditor from 'vditor'
import 'vditor/dist/index.css'

import { cn } from '@/lib/utils'
import { useTheme } from '@/lib/theme'
import { previewUrlForFileLink } from '@/lib/project-files'

const VDITOR_ASSETS = '/vendor/vditor'

const FORMAT_TOOLBAR = [
  'headings',
  'bold',
  'italic',
  'strike',
  'quote',
  'line',
  'list',
  'ordered-list',
  'link',
  'inline-code',
  'code',
  'undo',
  'redo',
]

type VditorAccessibilityProps = {
  ariaLabel?: string
  ariaLabelledBy?: string
  ariaDescribedBy?: string
}

export interface MarkdownEditingSurface {
  element: HTMLElement
  getRange(): Range
  insertLink(range: Range, label: string, href: string, image?: boolean): void
  insertText(range: Range, text: string): void
}

type MarkdownEditorProps = VditorAccessibilityProps & {
  initialMarkdown: string
  onChange: (markdown: string) => void
  onReady?: (editor: Vditor) => void
  onEditorReady?: (surface: MarkdownEditingSurface | null) => void
  disabled?: boolean
  id?: string
  placeholder?: string
  className?: string
}

export type VditorMarkdownViewerProps = VditorAccessibilityProps & {
  markdown: string
  className?: string
  /** REQ-59:[[双链]]解析结果;提供时把 [[..]] 渲染为可点 wiki 链接(断链可点创建)。 */
  wikiLinks?: {
    outgoing: { raw_text: string; display: string | null; section: string | null; to_code: string | null; to_title: string | null; broken: boolean }[]
  }
}

// 与后端 _LINK_RE 对齐:[[目标|显示]]/[[目标#小节]];目标/显示不含 [ ] |
const WIKI_LINK_RE = /\[\[\s*([^\[\]|]+?)\s*(?:\|\s*([^\[\]|]+?)\s*)?\]\]/g

function renderWikiLinks(markdown: string, links: VditorMarkdownViewerProps['wikiLinks']): string {
  if (!links || links.outgoing.length === 0) return markdown
  const byTarget = new Map<string, { to_code: string | null; broken: boolean }>()
  for (const link of links.outgoing) {
    if (!byTarget.has(link.raw_text)) byTarget.set(link.raw_text, { to_code: link.to_code, broken: link.broken })
  }
  return markdown.replace(WIKI_LINK_RE, (whole, target: string, display?: string) => {
    const resolved = byTarget.get(target.trim())
    if (!resolved) return whole
    const text = (display ?? target).trim()
    if (resolved.broken || !resolved.to_code) {
      return `<a href="#wiki-create" class="wiki-link wiki-link-broken" data-wiki-create="${escapeAttr(target.trim())}" title="断链:点击创建该页面">${escapeHtml(text)}<sup>+</sup></a>`
    }
    return `<a href="/documents/wiki/${encodeURIComponent(resolved.to_code)}" class="wiki-link" data-wiki-code="${escapeAttr(resolved.to_code)}">${escapeHtml(text)}</a>`
  })
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function escapeAttr(value: string): string {
  return escapeHtml(value).replace(/"/g, '&quot;')
}

function applyAccessibility(
  element: HTMLElement,
  { ariaLabel, ariaLabelledBy, ariaDescribedBy }: VditorAccessibilityProps,
) {
  if (ariaLabel) element.setAttribute('aria-label', ariaLabel)
  else element.removeAttribute('aria-label')

  if (ariaLabelledBy) element.setAttribute('aria-labelledby', ariaLabelledBy)
  else element.removeAttribute('aria-labelledby')

  if (ariaDescribedBy) element.setAttribute('aria-describedby', ariaDescribedBy)
  else element.removeAttribute('aria-describedby')
}

function bindFilePreviews(target: HTMLElement) {
  for (const image of target.querySelectorAll<HTMLImageElement>('img[src]')) {
    const href = image.getAttribute('src') ?? ''
    const previewUrl = previewUrlForFileLink(href)
    if (!previewUrl) continue
    image.addEventListener('error', () => {
      const link = document.createElement('a')
      link.href = href
      link.textContent = image.alt || '查看文件'
      image.replaceWith(link)
    }, { once: true })
    image.src = previewUrl
  }
}

function makeSurface(editor: Vditor, element: HTMLElement, sync: () => void): MarkdownEditingSurface {
  const doc = element.ownerDocument

  function getRange() {
    const selection = doc.getSelection()
    if (selection?.rangeCount && element.contains(selection.getRangeAt(0).commonAncestorContainer)) {
      return selection.getRangeAt(0).cloneRange()
    }
    const saved = editor.vditor.wysiwyg?.range
    if (saved && element.contains(saved.commonAncestorContainer)) return saved.cloneRange()
    const end = doc.createRange()
    end.selectNodeContents(element.lastElementChild ?? element)
    end.collapse(false)
    return end
  }

  function replace(range: Range, inline: Node, trailingSpace = false) {
    if (!element.contains(range.commonAncestorContainer)) return
    const end = range.endContainer
    if (trailingSpace && end instanceof Text && /^[ \u00a0]/u.test(end.data.slice(range.endOffset))) {
      range.setEnd(end, range.endOffset + 1)
    }
    const selection = doc.getSelection()
    if (!selection) return
    element.focus({ preventScroll: true })
    selection.removeAllRanges()
    selection.addRange(range)
    editor.vditor.undo?.addToUndoStack(editor.vditor)
    range.deleteContents()
    if (range.startContainer === element) {
      const paragraph = doc.createElement('p')
      paragraph.dataset.block = '0'
      range.insertNode(paragraph)
      range.setStart(paragraph, 0)
      range.collapse(true)
    }
    const fragment = doc.createDocumentFragment()
    fragment.append(inline)
    if (trailingSpace) fragment.append(doc.createTextNode(' '))
    const last = fragment.lastChild!
    range.insertNode(fragment)
    range.selectNodeContents(last)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
    editor.vditor.undo?.addToUndoStack(editor.vditor)
    sync()
  }

  return {
    element, getRange,
    insertText(range, text) { replace(range, doc.createTextNode(text)) },
    insertLink(range, label, href, image = false) {
      if (!/^\/(?!\/)[^\s<>\\]+$/u.test(href)) return
      if (image) {
        const img = doc.createElement('img')
        // Lute cannot round-trip some image filenames (e.g. unmatched brackets
        // or quotes) as Markdown alt text. Use typographic equivalents for
        // punctuation only when that filename would lose its description.
        img.alt = label
        img.setAttribute('src', href)
        const template = doc.createElement('template')
        const markdown = editor.vditor.lute.VditorDOM2Md(`<p data-block="0">${img.outerHTML}</p>`)
        template.innerHTML = editor.vditor.lute.Md2VditorDOM(markdown)
        if (template.content.querySelector('img')?.alt !== label) {
          let openingQuote = true
          img.alt = label.replace(/["\\[\]`<>*_~&]/gu, (character) => {
            if (character !== '"') return String.fromCharCode(character.charCodeAt(0) + 0xfee0)
            const quote = openingQuote ? '“' : '”'
            openingQuote = !openingQuote
            return quote
          })
        }
        const preview = previewUrlForFileLink(href)
        if (preview) img.srcset = preview
        replace(range, img, true)
      } else {
        // Use Vditor's own inline DOM for escaped brackets and punctuation in titles.
        const escaped = label.replace(/\s+/gu, ' ').replace(/[\\[\]`<>*_~&]/gu, '\\$&')
        const template = doc.createElement('template')
        template.innerHTML = editor.vditor.lute.Md2VditorDOM(`[${escaped}](<${href}>)`)
        const link = template.content.querySelector('a')
        if (link) replace(range, link, true)
      }
    },
  }
}

function observeEditorImages(element: HTMLElement) {
  const apply = (img: HTMLImageElement) => {
    const preview = previewUrlForFileLink(img.getAttribute('src') ?? '')
    if (preview) img.srcset = preview
    else if (img.srcset.startsWith('/api/v2/projects/')) img.removeAttribute('srcset')
  }
  const visit = (node: Node) => {
    if (node instanceof HTMLImageElement) apply(node)
    else if (node instanceof HTMLElement) node.querySelectorAll('img').forEach(apply)
  }
  visit(element)
  const observer = new MutationObserver((changes) => {
    for (const change of changes) {
      if (change.type === 'attributes') visit(change.target)
      else change.addedNodes.forEach(visit)
    }
  })
  observer.observe(element, { attributes: true, attributeFilter: ['src'], childList: true, subtree: true })
  return () => observer.disconnect()
}

export function WysiwygMarkdownEditor({
  initialMarkdown,
  onChange,
  onReady,
  onEditorReady,
  disabled = false,
  id,
  placeholder = '输入正文',
  className,
  ariaLabel,
  ariaLabelledBy,
  ariaDescribedBy,
}: MarkdownEditorProps) {
  const { theme } = useTheme()
  const hostRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<Vditor | null>(null)
  const initialMarkdownRef = useRef(initialMarkdown)
  const pendingMarkdownRef = useRef(initialMarkdown)
  const latestLocalMarkdownRef = useRef(initialMarkdown)
  const onChangeRef = useRef(onChange)
  const onReadyRef = useRef(onReady)
  const onEditorReadyRef = useRef(onEditorReady)
  const initialThemeRef = useRef(theme)
  const initialPlaceholderRef = useRef(placeholder)
  const disabledRef = useRef(disabled)
  const readyRef = useRef(false)
  const [ready, setReady] = useState(false)

  onChangeRef.current = onChange
  onReadyRef.current = onReady
  onEditorReadyRef.current = onEditorReady
  disabledRef.current = disabled

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let destroyed = false
    let unbind: (() => void) | undefined
    const mount = document.createElement('div')
    host.replaceChildren(mount)
    function publish(markdown: string) {
      if (destroyed || markdown === latestLocalMarkdownRef.current) return
      latestLocalMarkdownRef.current = markdown
      onChangeRef.current(markdown)
    }
    const editor = new Vditor(mount, {
      mode: 'wysiwyg',
      lang: 'zh_CN',
      theme: initialThemeRef.current === 'dark' ? 'dark' : 'classic',
      preview: { theme: { current: initialThemeRef.current } },
      hint: { emoji: {} },
      value: initialMarkdownRef.current,
      placeholder: escapeAttr(initialPlaceholderRef.current),
      toolbar: FORMAT_TOOLBAR,
      toolbarConfig: { hide: true, pin: false },
      customWysiwygToolbar(context, popover) {
        popover.dataset.toolbarContext = context
        popover.querySelectorAll('input, textarea').forEach((field) => field.setAttribute('autocomplete', 'off'))
      },
      cache: { enable: false },
      cdn: VDITOR_ASSETS,
      input: publish,
      after() {
        if (destroyed) {
          editor.destroy()
          return
        }
        readyRef.current = true
        const pendingMarkdown = pendingMarkdownRef.current
        if (pendingMarkdown !== latestLocalMarkdownRef.current && editor.getValue() !== pendingMarkdown) {
          editor.setValue(pendingMarkdown, true)
          latestLocalMarkdownRef.current = pendingMarkdown
        }
        // Vditor normalizes the final newline on first render. Merely focusing an
        // existing document must not mark it dirty.
        latestLocalMarkdownRef.current = editor.getValue()
        const editable = mount.querySelector<HTMLElement>('.vditor-wysiwyg > pre.vditor-reset')
        if (editable) {
          const sync = () => {
            if (!editor.vditor.wysiwyg?.composingLock) publish(editor.getValue())
          }
          const syncCommand = (event: KeyboardEvent) => {
            if (event.ctrlKey || event.metaKey || event.key === 'Enter' || event.key === 'Tab') sync()
          }
          const stopImages = observeEditorImages(editable)
          // Vditor debounces input together with undo. Flush native edits before
          // the user can switch focus and save a stale controlled value.
          editable.addEventListener('input', sync)
          editable.addEventListener('keyup', syncCommand)
          editable.addEventListener('compositionend', sync)
          editable.addEventListener('focusout', sync)
          onEditorReadyRef.current?.(makeSurface(editor, editable, sync))
          unbind = () => {
            stopImages()
            editable.removeEventListener('input', sync)
            editable.removeEventListener('keyup', syncCommand)
            editable.removeEventListener('compositionend', sync)
            editable.removeEventListener('focusout', sync)
            onEditorReadyRef.current?.(null)
          }
        }
        if (disabledRef.current) editor.disabled()
        setReady(true)
        onReadyRef.current?.(editor)
      },
    })

    editorRef.current = editor

    return () => {
      destroyed = true
      unbind?.()
      mount.remove()
      if (editorRef.current === editor) editorRef.current = null
      if (readyRef.current) {
        readyRef.current = false
        editor.destroy()
      }
    }
  }, [])

  useEffect(() => {
    pendingMarkdownRef.current = initialMarkdown
    if (!readyRef.current || initialMarkdown === latestLocalMarkdownRef.current) return

    const editor = editorRef.current
    if (editor && editor.getValue() !== initialMarkdown) {
      editor.setValue(initialMarkdown, true)
      latestLocalMarkdownRef.current = editor.getValue()
    }
  }, [initialMarkdown])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || !readyRef.current) return
    if (disabled) editor.disabled()
    else editor.enable()
  }, [disabled])

  useEffect(() => {
    if (ready) editorRef.current?.setTheme(theme === 'dark' ? 'dark' : 'classic', theme)
  }, [ready, theme])

  useEffect(() => {
    const host = hostRef.current
    const editor = editorRef.current
    if (!host || !editor || !ready) return
    const editorHost = host
    const activeEditor = editor

    let toolbarVisible = false
    let blurTimer: number | undefined

    function setToolbarVisible(visible: boolean, range?: Range) {
      if (toolbarVisible !== visible) {
        toolbarVisible = visible
        activeEditor.updateToolbarConfig({ hide: !visible, pin: false })
      }
      if (!visible || !range) return

      const toolbar = editorHost.querySelector<HTMLElement>('.vditor-toolbar')
      const hostBox = editorHost.getBoundingClientRect()
      const selectionBox = range.getBoundingClientRect()
      if (!toolbar || !selectionBox.width) return
      const maxLeft = Math.max(0, hostBox.width - toolbar.offsetWidth)
      toolbar.style.left = `${Math.min(maxLeft, Math.max(0, selectionBox.left - hostBox.left))}px`
      toolbar.style.top = `${Math.max(0, selectionBox.top - hostBox.top - toolbar.offsetHeight - 10)}px`
    }

    function updateToolbarFromSelection() {
      const selection = window.getSelection()
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        setToolbarVisible(false)
        return
      }
      const range = selection.getRangeAt(0)
      setToolbarVisible(editorHost.contains(range.commonAncestorContainer), range)
    }

    function hideAfterFocusLeaves() {
      window.clearTimeout(blurTimer)
      blurTimer = window.setTimeout(() => {
        if (!editorHost.contains(document.activeElement)) setToolbarVisible(false)
      }, 0)
    }

    document.addEventListener('selectionchange', updateToolbarFromSelection)
    editorHost.addEventListener('focusout', hideAfterFocusLeaves)
    return () => {
      window.clearTimeout(blurTimer)
      document.removeEventListener('selectionchange', updateToolbarFromSelection)
      editorHost.removeEventListener('focusout', hideAfterFocusLeaves)
    }
  }, [ready])

  useEffect(() => {
    const editable = hostRef.current?.querySelector<HTMLElement>('.vditor-wysiwyg > pre.vditor-reset')
    if (!editable) return
    editable.setAttribute('role', 'textbox')
    editable.setAttribute('aria-multiline', 'true')
    editable.setAttribute('aria-readonly', String(disabled))
    editable.setAttribute('placeholder', placeholder)
    if (id) editable.id = id
    else editable.removeAttribute('id')
    applyAccessibility(editable, { ariaLabel, ariaLabelledBy, ariaDescribedBy })
  }, [ready, ariaLabel, ariaLabelledBy, ariaDescribedBy, id, disabled, placeholder])

  return (
    <div className={cn('markdown-wysiwyg relative', className)}>
      {!ready && <div className="absolute inset-0 z-10 bg-background/80" role="status">正在加载编辑器…</div>}
      <div ref={hostRef} aria-busy={!ready} inert={!ready} />
    </div>
  )
}

export function VditorMarkdownViewer({
  markdown,
  className,
  wikiLinks,
  ariaLabel,
  ariaLabelledBy,
  ariaDescribedBy,
}: VditorMarkdownViewerProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let cancelled = false
    const renderTarget = document.createElement('div')
    host.setAttribute('aria-busy', 'true')
    void Vditor.preview(renderTarget, renderWikiLinks(markdown, wikiLinks), {
      cdn: VDITOR_ASSETS, mode: theme, theme: { current: theme },
    })
      .then(() => {
        if (cancelled) return
        bindFilePreviews(renderTarget)
        host.replaceChildren(...renderTarget.childNodes)
        applyAccessibility(host, { ariaLabel, ariaLabelledBy, ariaDescribedBy })
        host.setAttribute('aria-busy', 'false')
      })
      .catch(() => {
        if (!cancelled) host.setAttribute('aria-busy', 'false')
      })

    return () => {
      cancelled = true
    }
  }, [markdown, wikiLinks, ariaLabel, ariaLabelledBy, ariaDescribedBy, theme])

  return <div ref={hostRef} className={cn('vditor-reset', className)} />
}
