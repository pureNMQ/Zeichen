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
      toolbar: IR_TOOLBAR,
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
    void Vditor.preview(renderTarget, markdown, { cdn: VDITOR_CDN, mode: 'light' })
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
  }, [markdown, ariaLabel, ariaLabelledBy, ariaDescribedBy])

  return <div ref={hostRef} className={cn('vditor-reset', className)} />
}
