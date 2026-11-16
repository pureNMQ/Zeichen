import { useEffect, useRef, useState } from 'react'
import Vditor from 'vditor'
import 'vditor/dist/index.css'

import { cn } from '@/lib/utils'

const VDITOR_CDN = 'https://cdn.jsdelivr.net/npm/vditor@3.11.2'

const IR_TOOLBAR = [
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

export type VditorIrEditorProps = VditorAccessibilityProps & {
  initialMarkdown: string
  onChange: (markdown: string) => void
  onReady?: (editor: Vditor) => void
  disabled?: boolean
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

export function VditorIrEditor({
  initialMarkdown,
  onChange,
  onReady,
  disabled = false,
  className,
  ariaLabel,
  ariaLabelledBy,
  ariaDescribedBy,
}: VditorIrEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<Vditor | null>(null)
  const initialMarkdownRef = useRef(initialMarkdown)
  const pendingMarkdownRef = useRef(initialMarkdown)
  const latestLocalMarkdownRef = useRef(initialMarkdown)
  const onChangeRef = useRef(onChange)
  const onReadyRef = useRef(onReady)
  const disabledRef = useRef(disabled)
  const readyRef = useRef(false)
  const [ready, setReady] = useState(false)

  onChangeRef.current = onChange
  onReadyRef.current = onReady
  disabledRef.current = disabled

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let destroyed = false
    const editor = new Vditor(host, {
      mode: 'ir',
      value: initialMarkdownRef.current,
      placeholder: '输入 / 添加内容，或直接开始写作',
      toolbar: IR_TOOLBAR,
      toolbarConfig: { hide: true, pin: false },
      cache: { enable: false },
      cdn: VDITOR_CDN,
      input(markdown) {
        latestLocalMarkdownRef.current = markdown
        onChangeRef.current(markdown)
      },
      after() {
        if (destroyed) {
          editor.destroy()
          return
        }
        readyRef.current = true
        const pendingMarkdown = pendingMarkdownRef.current
        if (pendingMarkdown !== latestLocalMarkdownRef.current && editor.getValue() !== pendingMarkdown) {
          editor.setValue(pendingMarkdown, true)
        }
        if (disabledRef.current) editor.disabled()
        setReady(true)
        onReadyRef.current?.(editor)
      },
    })

    editorRef.current = editor

    return () => {
      destroyed = true
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
    }
  }, [initialMarkdown])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || !readyRef.current) return
    if (disabled) editor.disabled()
    else editor.enable()
  }, [disabled])

  useEffect(() => {
    const host = hostRef.current
    const editor = editorRef.current
    if (!host || !editor || !ready) return
    const editorHost = host
    const activeEditor = editor

    let toolbarVisible = false
    let blurTimer: number | undefined

    function setToolbarVisible(visible: boolean, range?: Range) {
      if (toolbarVisible === visible) return
      toolbarVisible = visible
      activeEditor.updateToolbarConfig({ hide: !visible, pin: false })
      if (!visible || !range) return

      const toolbar = editorHost.querySelector<HTMLElement>('.vditor-toolbar')
      const hostBox = editorHost.getBoundingClientRect()
      const selectionBox = range.getBoundingClientRect()
      if (!toolbar || !selectionBox.width) return
      toolbar.style.left = `${Math.max(0, selectionBox.left - hostBox.left)}px`
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
    const editable = hostRef.current?.querySelector<HTMLElement>('pre.vditor-reset[contenteditable="true"]')
    if (!editable) return
    editable.setAttribute('role', 'textbox')
    editable.setAttribute('aria-multiline', 'true')
    applyAccessibility(editable, { ariaLabel, ariaLabelledBy, ariaDescribedBy })
  }, [ready, ariaLabel, ariaLabelledBy, ariaDescribedBy])

  return (
    <div className={cn('relative', className)}>
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

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let cancelled = false
    const renderTarget = document.createElement('div')
    host.setAttribute('aria-busy', 'true')
    void Vditor.preview(renderTarget, renderWikiLinks(markdown, wikiLinks), { cdn: VDITOR_CDN, mode: 'light' })
      .then(() => {
        if (cancelled) return
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
  }, [markdown, wikiLinks, ariaLabel, ariaLabelledBy, ariaDescribedBy])

  return <div ref={hostRef} className={cn('vditor-reset', className)} />
}
