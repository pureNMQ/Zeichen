import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal, flushSync } from 'react-dom'
import { autoUpdate, computePosition, flip, hide, offset, shift, size } from '@floating-ui/dom'
import { AtSign, FileUp, Image as ImageIcon, Link2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { WysiwygMarkdownEditor, type MarkdownEditingSurface } from '@/components/vditor-ir-editor'
import { caretRect, inlineCompletion, sameRange, type InlineCompletion } from '@/components/markdown-completion'
import { cn } from '@/lib/utils'

export type CompletionMode = 'people' | 'reference' | 'image'

export type CompletionCandidate = {
  id: string
  label: string
  kind: 'member' | 'agent' | 'wiki' | 'requirement' | 'task' | 'file'
  /** Stable, project-scoped route returned by the server. */
  href: string
  detail?: string
  thumbnailUrl?: string
}

/** Supply a lookup bound to the current project's permissions. */
export type CompletionLookup = (
  mode: CompletionMode,
  query: string,
  signal: AbortSignal,
) => Promise<readonly CompletionCandidate[]>

export type ComposerUpload = (
  file: File,
  requestId: string,
  signal: AbortSignal,
  onProgress: (percent: number) => void,
) => Promise<{ name: string; href: string; image: boolean }>

type MarkdownComposerProps = {
  value: string
  onChange: (markdown: string) => void
  lookup: CompletionLookup
  upload?: ComposerUpload
  onUploadPending?: (uploading: boolean) => void
  id?: string
  label?: string
  disabled?: boolean
  className?: string
}


type Picker = { mode: CompletionMode; query: string; replace: Range; caret: Range; sourceValue: string }
type SearchRequest = { lookup: CompletionLookup; mode: CompletionMode; query: string; attempt: number }
type SearchResult = { request: SearchRequest; items: readonly CompletionCandidate[]; failed: boolean }

const kindLabels = { member: '成员', agent: 'Agent', wiki: 'Wiki', requirement: '需求', file: '文件', task: '任务' }
const pickerLabels = { people: '查找成员', reference: '查找引用', image: '查找图片' }

export function MarkdownComposer({
  value, onChange, lookup, upload, onUploadPending, id, label = 'Markdown 正文', disabled = false, className,
}: MarkdownComposerProps) {
  const [surface, setSurface] = useState<MarkdownEditingSurface | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const savedRange = useRef<Range | null>(null)
  const uploadController = useRef<AbortController | null>(null)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [failedUpload, setFailedUpload] = useState<{ file: File; requestId: string } | null>(null)
  const [inline, setInline] = useState<InlineCompletion | null>(null)
  const [picker, setPicker] = useState<Picker | null>(null)
  const composing = useRef(false)
  const dismissed = useRef<InlineCompletion | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [highlight, setHighlight] = useState<{ request: SearchRequest; index: number } | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const listId = useId()
  const unavailable = disabled || uploadProgress !== null
  const explicit = picker?.sourceValue === value ? picker : null
  const active = unavailable ? null : explicit ?? inline
  const mode = active?.mode
  const query = active?.query.trim() ?? ''
  const request = useMemo<SearchRequest | null>(() => mode ? { lookup, mode, query, attempt: retryCount } : null,
    [lookup, mode, query, retryCount])
  const current = result?.request === request ? result : null
  const items = current?.items ?? []
  const activeIndex = highlight?.request === request && highlight.index < items.length ? highlight.index : 0
  const activeId = items.length ? listId + '-' + activeIndex : undefined

  const syncSelection = useCallback(() => {
    if (!surface || composing.current || picker || unavailable) return
    const selected = surface.element.ownerDocument.getSelection()
    if (!surface.element.contains(document.activeElement) || !selected?.rangeCount ||
        !surface.element.contains(selected.anchorNode) || !surface.element.contains(selected.focusNode)) {
      setInline(null)
      return
    }
    savedRange.current = selected.getRangeAt(0).cloneRange()
    const next = inlineCompletion(surface.element)
    const skip = dismissed.current
    if (next && skip && next.query === skip.query && next.mode === skip.mode && sameRange(next.caret, skip.caret)) {
      setInline(null)
      return
    }
    dismissed.current = null
    setInline((prev) => next && prev && next.query === prev.query && next.mode === prev.mode &&
      sameRange(next.caret, prev.caret) && sameRange(next.replace, prev.replace) ? prev : next)
  }, [surface, picker, unavailable])

  useEffect(() => {
    document.addEventListener('selectionchange', syncSelection)
    return () => document.removeEventListener('selectionchange', syncSelection)
  }, [syncSelection])
  const uploadPendingRef = useRef(onUploadPending)
  uploadPendingRef.current = onUploadPending
  useEffect(() => () => {
    if (uploadController.current) {
      uploadController.current.abort()
      uploadPendingRef.current?.(false)
    }
  }, [])

  useEffect(() => {
    if (!request) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const candidates = await request.lookup(request.mode, request.query, controller.signal)
        if (controller.signal.aborted) return
        const items = candidates.filter(({ href }) => /^\/(?!\/)[^\s<>\\]+$/u.test(href))
        setResult({ request, items, failed: false })
      } catch {
        if (!controller.signal.aborted) setResult({ request, items: [], failed: true })
      }
    }, 120)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [request])

  useLayoutEffect(() => {
    if (!surface) return
    const el = surface.element
    el.setAttribute('aria-autocomplete', 'list')
    if (mode && !explicit) el.setAttribute('aria-controls', listId)
    else el.removeAttribute('aria-controls')
    if (activeId && !explicit) el.setAttribute('aria-activedescendant', activeId)
    else el.removeAttribute('aria-activedescendant')
  }, [activeId, explicit, listId, mode, surface])
  useEffect(() => {
    if (picker && (unavailable || picker.sourceValue !== value)) {
      setPicker(null)
      savedRange.current = null
    }
    if (unavailable) setInline(null)
  }, [picker, unavailable, value])

  useEffect(() => {
    if (!mode) return
    function outside(event: PointerEvent) {
      const target = event.target
      if (!(target instanceof Node) || rootRef.current?.contains(target) || menuRef.current?.contains(target)) return
      setPicker(null)
      setInline(null)
    }
    document.addEventListener('pointerdown', outside, true)
    return () => document.removeEventListener('pointerdown', outside, true)
  }, [mode])

  const pickerMode = explicit?.mode
  useLayoutEffect(() => { if (pickerMode) searchRef.current?.focus({ preventScroll: true }) }, [pickerMode])
  useEffect(() => {
    const list = listRef.current
    const option = activeId ? document.getElementById(activeId) : null
    if (!list || !option) return
    if (option.offsetTop < list.scrollTop) list.scrollTop = option.offsetTop
    else if (option.offsetTop + option.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = option.offsetTop + option.offsetHeight - list.clientHeight
    }
  }, [activeId])

  const anchor = active?.caret
  useLayoutEffect(() => {
    if (!anchor || !surface || !menuRef.current) return
    const menu = menuRef.current
    const reference = { contextElement: surface.element, getBoundingClientRect: () => caretRect(anchor) }
    let sequence = 0
    const update = async () => {
      const seq = ++sequence
      const { x, y, middlewareData } = await computePosition(reference, menu, {
        strategy: 'fixed', placement: 'bottom-start',
        middleware: [offset(5), flip({ padding: 8 }), shift({ padding: 8 }),
          size({ padding: 8, apply({ availableHeight, availableWidth }) {
            menu.style.maxHeight = Math.max(0, Math.min(280, availableHeight)) + 'px'
            menu.style.maxWidth = Math.max(0, availableWidth) + 'px'
          } }), hide({ padding: -1 })],
      })
      if (seq !== sequence) return
      Object.assign(menu.style, { left: x + 'px', top: y + 'px', visibility: middlewareData.hide?.referenceHidden ? 'hidden' : 'visible' })
    }
    const stop = autoUpdate(reference, menu, update)
    return () => { sequence++; stop() }
  }, [anchor, surface])

  function rangeForAction() {
    if (!surface) return null
    const live = document.getSelection()
    if (live?.rangeCount && surface.element.contains(live.anchorNode) && surface.element.contains(live.focusNode)) {
      return live.getRangeAt(0).cloneRange()
    }
    return savedRange.current && surface.element.contains(savedRange.current.commonAncestorContainer)
      ? savedRange.current.cloneRange() : surface.getRange()
  }

  function openPicker(mode: CompletionMode) {
    if (unavailable) return
    const range = rangeForAction()
    if (!range) return
    setInline(null)
    setPicker({ mode, query: '', caret: range.cloneRange(), replace: range, sourceValue: value })
  }

  function closeMenu(restoreFocus = false) {
    dismissed.current = inline
    setPicker(null)
    setInline(null)
    if (restoreFocus && explicit && surface) {
      surface.element.focus({ preventScroll: true })
      const selection = document.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(explicit.replace)
    }
  }

  function choose(candidate: CompletionCandidate) {
    if (!surface || !active) return
    const target = explicit ?? inlineCompletion(surface.element)
    if (!target || target.mode !== mode || target.query.trim() !== query) return
    closeMenu()
    surface.insertLink(target.replace, mode === 'people' ? '@' + candidate.label : candidate.label, candidate.href, mode === 'image')
  }

  async function uploadFile(file: File, requestId: string) {
    if (!upload || !surface || unavailable || uploadController.current) return
    const replace = rangeForAction()
    if (!replace) return
    const controller = new AbortController()
    uploadController.current = controller
    setUploadError(null)
    setFailedUpload(null)
    setUploadProgress(0)
    onUploadPending?.(true)
    closeMenu()
    try {
      const saved = await upload(file, requestId, controller.signal, setUploadProgress)
      if (!controller.signal.aborted) {
        // Restore editability before putting the caret back in the uploaded document link.
        flushSync(() => setUploadProgress(null))
        surface.insertLink(replace, saved.name, saved.href, saved.image)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setUploadError(error instanceof Error ? error.message : '文件上传失败，请重试。')
        setFailedUpload({ file, requestId })
      }
    } finally {
      uploadController.current = null
      if (!controller.signal.aborted) {
        setUploadProgress(null)
        onUploadPending?.(false)
      }
    }
  }

  function acceptFiles(files: FileList) {
    if (!files.length || unavailable || uploadController.current) return
    if (files.length > 1) {
      setFailedUpload(null)
      setUploadError('请一次上传一份文件。')
      return
    }
    void uploadFile(files[0], crypto.randomUUID())
  }

  function handleKeys(event: KeyboardEvent) {
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229 || composing.current) return
    if (surface?.element.contains(event.target as Node) && event.altKey && !event.ctrlKey && !event.metaKey &&
        event.key.toLowerCase() === 'k') {
      event.preventDefault()
      event.stopPropagation()
      openPicker(event.shiftKey ? 'image' : 'reference')
      return
    }
    if (!request) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closeMenu(true)
    } else if (items.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault()
      event.stopPropagation()
      const index = (activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
      setHighlight({ request, index })
    } else if (items.length && !event.shiftKey && (event.key === 'Enter' || event.key === 'Tab')) {
      event.preventDefault()
      event.stopPropagation()
      choose(items[activeIndex])
    }
  }

  const menuPortal = surface?.element.closest('[role="dialog"]') ?? document.body
  return <div ref={rootRef} className={cn('min-w-0 space-y-1', className)}
    onKeyDownCapture={handleKeys}
    onInputCapture={() => { queueMicrotask(syncSelection) }}
    onKeyUp={syncSelection}
    onClick={syncSelection}
    onCompositionStartCapture={() => { composing.current = true; setInline(null) }}
    onCompositionEndCapture={() => { composing.current = false; queueMicrotask(syncSelection) }}
    onBlur={(event) => {
      if (event.currentTarget.contains(event.relatedTarget) || menuRef.current?.contains(event.relatedTarget)) return
      setInline(null)
      setPicker(null)
    }}
    onDragOverCapture={(event) => {
      if (upload && event.dataTransfer.types.includes('Files')) event.preventDefault()
    }}
    onDropCapture={(event) => {
      if (!upload || !event.dataTransfer.files.length) return
      event.preventDefault()
      event.stopPropagation()
      acceptFiles(event.dataTransfer.files)
    }}
    onPasteCapture={(event) => {
      if (!upload || !event.clipboardData.files.length) return
      event.preventDefault()
      event.stopPropagation()
      acceptFiles(event.clipboardData.files)
    }}>
    <div className="flex flex-wrap gap-0.5">
      <Button type="button" size="sm" variant="ghost" disabled={unavailable || !surface}
        title="键入 @ 提及成员或 Agent" onMouseDown={(event) => event.preventDefault()}
        onClick={() => openPicker('people')}><AtSign aria-hidden="true" />提及</Button>
      <Button type="button" size="sm" variant="ghost" disabled={unavailable || !surface} aria-keyshortcuts="Alt+K"
        title="键入 [[ 引用项目内容（Alt+K）" onMouseDown={(event) => event.preventDefault()}
        onClick={() => openPicker('reference')}><Link2 aria-hidden="true" />插入引用</Button>
      <Button type="button" size="sm" variant="ghost" disabled={unavailable || !surface} aria-keyshortcuts="Alt+Shift+K"
        title="键入 ![[ 引用项目图片（Alt+Shift+K）" onMouseDown={(event) => event.preventDefault()}
        onClick={() => openPicker('image')}><ImageIcon aria-hidden="true" />插入图片</Button>
      {upload && <>
        <input ref={fileInputRef} type="file" autoComplete="off" hidden aria-label="选择上传文件" disabled={unavailable}
          onChange={(event) => { if (event.currentTarget.files) acceptFiles(event.currentTarget.files); event.currentTarget.value = '' }} />
        <Button type="button" size="sm" variant="ghost" disabled={unavailable || !surface} onMouseDown={(event) => event.preventDefault()}
          onClick={() => fileInputRef.current?.click()}><FileUp aria-hidden="true" />上传文件</Button>
      </>}
      {failedUpload && <Button type="button" size="sm" variant="outline" disabled={unavailable}
        onClick={() => void uploadFile(failedUpload.file, failedUpload.requestId)}>重试上传</Button>}
    </div>
    <ErrorNotification message={uploadError} />
    {uploadProgress !== null && <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <progress aria-label="上传进度" max={100} value={uploadProgress} /><span>{uploadProgress}%</span>
    </div>}
    <WysiwygMarkdownEditor id={id} ariaLabel={label} initialMarkdown={value} onChange={onChange} onEditorReady={setSurface}
      disabled={unavailable} placeholder="输入正文，@ 提及成员，[[ 引用项目内容" />
    <ErrorNotification message={current?.failed ? '无法加载候选项，请重试。' : null} />
    {mode && createPortal(<div ref={menuRef} style={{ position: 'fixed', left: 0, top: 0 }}
      className="z-[60] flex w-[min(21rem,calc(100vw-1rem))] flex-col gap-1 overflow-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-md">
      {explicit && <Input ref={searchRef} role="combobox" aria-label={pickerLabels[mode]} placeholder={pickerLabels[mode]}
        aria-expanded="true" aria-autocomplete="list" aria-controls={listId} aria-activedescendant={activeId}
        className="h-8" autoComplete="off" value={explicit.query}
        onChange={(event) => setPicker({ ...explicit, query: event.currentTarget.value })} />}
      {!current && <p role="status" className="px-2 py-1 text-sm text-muted-foreground">加载候选项…</p>}
      {current?.failed && <Button type="button" size="sm" variant="ghost"
        onMouseDown={(event) => event.preventDefault()} onClick={() => setRetryCount((count) => count + 1)}>重试</Button>}
      {current && !current.failed && !items.length && <p role="status" className="px-2 py-1 text-sm text-muted-foreground">没有匹配项</p>}
      <ul id={listId} ref={listRef} role="listbox" aria-label="候选项" className="relative min-h-0 overflow-y-auto overscroll-contain">
        {items.map((candidate, index) => {
          const detail = [kindLabels[candidate.kind], candidate.detail].filter(Boolean).join(' · ')
          return <li key={candidate.kind + ':' + candidate.id} id={listId + '-' + index}
            role="option" title={candidate.label + ' · ' + detail} aria-label={candidate.label + ' ' + detail} aria-selected={index === activeIndex}
            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent aria-selected:bg-accent"
            onMouseDown={(event) => event.preventDefault()} onClick={() => choose(candidate)}>
            {mode === 'image' && candidate.thumbnailUrl && <img src={candidate.thumbnailUrl} alt="" className="size-7 rounded object-cover" />}
            <span className="min-w-0 flex-1 truncate">{candidate.label}</span>
            <span className="max-w-1/2 shrink-0 truncate text-xs text-muted-foreground">{detail}</span>
          </li>
        })}
      </ul>
    </div>, menuPortal)}
  </div>
}
