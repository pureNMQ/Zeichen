import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export type CompletionMode = 'people' | 'reference' | 'image'

export type CompletionCandidate = {
  id: string
  label: string
  kind: 'member' | 'agent' | 'wiki' | 'requirement' | 'file'
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

type Selection = { start: number; end: number }
type Picker = { mode: Exclude<CompletionMode, 'people'>; selection: Selection; value: string; query: string }
type SearchRequest = { lookup: CompletionLookup; mode: CompletionMode; query: string; attempt: number }
type SearchResult = { request: SearchRequest; items: readonly CompletionCandidate[]; failed: boolean }

const candidateKinds: Record<CompletionCandidate['kind'], string> = {
  member: '成员',
  agent: 'Agent',
  wiki: 'Wiki',
  requirement: '需求',
  file: '文件',
}

function readSelection(editor: HTMLTextAreaElement): Selection {
  return { start: editor.selectionStart, end: editor.selectionEnd }
}

function getMention(value: string, selection: Selection) {
  if (selection.start !== selection.end) return null
  const before = value.slice(0, selection.start)
  const match = /(?:^|[\s(（【「，、：])@([^\s@()[\]{}<>\\,!?;:，。！？、；：]*)$/u.exec(before)
  if (!match) return null
  const suffix = /^[^\s@()[\]{}<>\\,!?;:，。！？、；：]*/u.exec(value.slice(selection.end))?.[0] ?? ''
  return {
    query: match[1],
    selection: { start: before.length - match[1].length - 1, end: selection.end + suffix.length },
  }
}

function formatLink(candidate: Pick<CompletionCandidate, 'label' | 'href'>, mode: CompletionMode): string {
  const name = candidate.label.replace(/\s+/gu, ' ').replace(/[\\[\]`<>*_~&]/gu, '\\$&')
  const label = mode === 'people' ? `@${name}` : name
  return `${mode === 'image' ? '!' : ''}[${label}](<${candidate.href}>)`
}

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

export function MarkdownComposer({
  value, onChange, lookup, upload, onUploadPending, id, label = 'Markdown 正文', disabled = false, className,
}: MarkdownComposerProps) {
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const pendingCaretRef = useRef<{ value: string; offset: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadController = useRef<AbortController | null>(null)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [failedUpload, setFailedUpload] = useState<{ file: File; requestId: string } | null>(null)
  const [selection, setSelection] = useState<Selection>({ start: 0, end: 0 })
  const [editorFocused, setEditorFocused] = useState(false)
  const [composing, setComposing] = useState(false)
  const [dismissedMention, setDismissedMention] = useState('')
  const [picker, setPicker] = useState<Picker | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [highlight, setHighlight] = useState<{ request: SearchRequest; index: number } | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const listId = useId()

  const unavailable = disabled || uploadProgress !== null
  const mention = !unavailable && editorFocused && !composing && !picker ? getMention(value, selection) : null
  const mentionKey = mention ? `${mention.selection.start}:${mention.query}` : ''
  const activeMention = mentionKey !== dismissedMention ? mention : null
  const activePicker = !unavailable && picker?.value === value ? picker : null
  const mode = activePicker?.mode ?? (activeMention ? 'people' : null)
  const query = activePicker?.query.trim() ?? activeMention?.query ?? ''
  const request = useMemo<SearchRequest | null>(
    () => mode ? { lookup, mode, query, attempt: retryCount } : null,
    [lookup, mode, query, retryCount],
  )
  const current = request && result?.request === request ? result : null
  const items = current?.items ?? []
  const activeIndex = highlight && highlight.request === request && highlight.index < items.length ? highlight.index : 0
  const activeId = items.length ? `${listId}-${activeIndex}` : undefined
  const pickerOpen = activePicker !== null

  useEffect(() => () => { uploadController.current?.abort() }, [])

  useEffect(() => {
    if (!request) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const candidates = await request.lookup(request.mode, request.query, controller.signal)
        if (controller.signal.aborted) return
        // Only save local stable paths. Preview URLs are used separately.
        const items = candidates.filter(({ href }) => /^\/(?!\/)[^\s<>\\]+$/u.test(href))
        setResult({ request, items, failed: false })
      } catch {
        if (!controller.signal.aborted) setResult({ request, items: [], failed: true })
      }
    }, 150)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [request])

  const pickerMode = activePicker?.mode
  useLayoutEffect(() => {
    if (pickerMode) searchRef.current?.focus()
  }, [pickerMode])

  useLayoutEffect(() => {
    const pending = pendingCaretRef.current
    if (!pending) return
    pendingCaretRef.current = null
    if (pending.value !== value) return
    editorRef.current?.focus()
    editorRef.current?.setSelectionRange(pending.offset, pending.offset)
  }, [value, pickerOpen, uploadProgress])

  useEffect(() => {
    const list = listRef.current
    const option = activeId ? document.getElementById(activeId) : null
    if (!list || !option) return
    const start = option.offsetTop
    const end = start + option.offsetHeight
    if (start < list.scrollTop) list.scrollTop = start
    if (end > list.scrollTop + list.clientHeight) list.scrollTop = end - list.clientHeight
  }, [activeId])

  function openPicker(mode: Picker['mode']) {
    const editor = editorRef.current
    if (!editor || unavailable) return
    setHighlight(null)
    setResult(null)
    setPicker({ mode, selection: readSelection(editor), value, query: '' })
    if (activePicker?.mode === mode) searchRef.current?.focus()
  }

  function closePicker() {
    setPicker(null)
    if (activeMention) setDismissedMention(mentionKey)
    if (activePicker) editorRef.current?.focus()
  }

  function insertLink(link: string, replace: Selection) {
    const tail = value.slice(replace.end)
    const suffix = /^\s/u.test(tail) ? '' : ' '
    const markdown = value.slice(0, replace.start) + link + suffix + tail
    const offset = replace.start + link.length + (tail.startsWith(' ') ? 1 : suffix.length)
    pendingCaretRef.current = { value: markdown, offset }
    setSelection({ start: offset, end: offset })
    onChange(markdown)
  }

  function insert(candidate: CompletionCandidate) {
    const replace = activePicker?.selection ?? activeMention?.selection
    if (!mode || !replace) return
    closePicker()
    insertLink(formatLink(candidate, mode), replace)
  }

  async function uploadFile(file: File, requestId: string) {
    const editor = editorRef.current
    if (!upload || !editor || unavailable || uploadController.current) return
    const replace = readSelection(editor)
    const controller = new AbortController()
    uploadController.current = controller
    setUploadError(null)
    setFailedUpload(null)
    setUploadProgress(0)
    onUploadPending?.(true)
    closePicker()
    try {
      const saved = await upload(file, requestId, controller.signal, setUploadProgress)
      if (!controller.signal.aborted) {
        insertLink(formatLink({ label: saved.name, href: saved.href }, saved.image ? 'image' : 'reference'), replace)
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setUploadError(error instanceof Error ? error.message : '文件上传失败，请重试。')
        setFailedUpload({ file, requestId })
        pendingCaretRef.current = { value, offset: replace.end }
      }
    } finally {
      uploadController.current = null
      if (!controller.signal.aborted) {
        setUploadProgress(null)
        onUploadPending?.(false)
      }
    }
  }

  function acceptFiles(files: FileList | null) {
    if (!files?.length || unavailable || uploadController.current) return
    if (files.length > 1) {
      setFailedUpload(null)
      setUploadError('请一次上传一份文件。')
      return
    }
    void uploadFile(files[0], crypto.randomUUID())
  }

  function handleKeys(event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing || composing) return
    if (event.currentTarget === editorRef.current && event.altKey && !event.ctrlKey && !event.metaKey &&
        (event.code === 'KeyK' || event.key.toLowerCase() === 'k')) {
      event.preventDefault()
      openPicker(event.shiftKey ? 'image' : 'reference')
      return
    }
    if (!request) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closePicker()
    } else if (items.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      const index = (activeIndex + step + items.length) % items.length
      setHighlight({ request, index })
    } else if (event.key === 'Enter' && !event.shiftKey) {
      if (items.length || activePicker) event.preventDefault()
      if (items.length) insert(items[activeIndex])
    }
  }

  return (
    <div
      className={cn('min-w-0 space-y-2', className)}
      onDragOver={(event) => {
        if (upload && event.dataTransfer.types.includes('Files')) event.preventDefault()
      }}
      onDrop={(event) => {
        if (!upload || !event.dataTransfer.files.length) return
        event.preventDefault()
        acceptFiles(event.dataTransfer.files)
      }}
      onBlur={(event) => {
        if (event.currentTarget.contains(event.relatedTarget)) return
        setEditorFocused(false)
        setPicker(null)
      }}
    >
      <div className="flex flex-wrap gap-1">
        <Button type="button" size="sm" variant="ghost" disabled={unavailable} aria-keyshortcuts="Alt+K" title="Alt+K"
          onClick={() => openPicker('reference')}>插入引用</Button>
        <Button type="button" size="sm" variant="ghost" disabled={unavailable} aria-keyshortcuts="Alt+Shift+K" title="Alt+Shift+K"
          onClick={() => openPicker('image')}>插入图片</Button>
        {upload && <>
          <input ref={fileInputRef} type="file" autoComplete="off" hidden aria-label="选择上传文件" disabled={unavailable}
            onChange={(event) => { acceptFiles(event.currentTarget.files); event.currentTarget.value = '' }} />
          <Button type="button" size="sm" variant="ghost" disabled={unavailable}
            onClick={() => fileInputRef.current?.click()}>上传文件</Button>
        </>}
        {failedUpload && <Button type="button" size="sm" variant="outline" disabled={unavailable}
          onClick={() => void uploadFile(failedUpload.file, failedUpload.requestId)}>重试上传</Button>}
      </div>
      <ErrorNotification message={uploadError} />
      {uploadProgress !== null && <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <progress aria-label="上传进度" max={100} value={uploadProgress} />
        <span>{uploadProgress}%</span>
      </div>}
      <Textarea
        id={id}
        ref={editorRef}
        aria-label={label}
        aria-autocomplete="list"
        aria-controls={activeMention ? listId : undefined}
        aria-activedescendant={activeMention ? activeId : undefined}
        autoComplete="off"
        placeholder="输入 Markdown，键入 @ 提及成员或 Agent"
        className="min-h-32 font-mono"
        disabled={unavailable}
        value={value}
        onFocus={(event) => {
          setEditorFocused(true)
          setSelection(readSelection(event.currentTarget))
        }}
        onSelect={(event) => setSelection(readSelection(event.currentTarget))}
        onChange={(event) => {
          setDismissedMention('')
          setSelection(readSelection(event.currentTarget))
          onChange(event.currentTarget.value)
        }}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={(event) => {
          setComposing(false)
          setSelection(readSelection(event.currentTarget))
        }}
        onKeyDown={handleKeys}
        onPaste={(event) => {
          if (!upload || !event.clipboardData.files.length) return
          event.preventDefault()
          acceptFiles(event.clipboardData.files)
        }}
      />
      {mode && (
        <div className="space-y-1 rounded-lg border bg-popover p-2 text-popover-foreground shadow-xs">
          {activePicker && (
            <Input
              ref={searchRef}
              role="combobox"
              aria-label={mode === 'image' ? '查找图片' : '查找引用'}
              aria-expanded="true"
              aria-autocomplete="list"
              aria-controls={listId}
              aria-activedescendant={activeId}
              autoComplete="off"
              value={activePicker.query}
              onChange={(event) => setPicker({ ...activePicker, query: event.currentTarget.value })}
              onKeyDown={handleKeys}
            />
          )}
          <ErrorNotification message={current?.failed ? '无法加载候选项，请重试。' : null} />
          {!current && <p role="status" className="px-2 py-1 text-sm text-muted-foreground">加载候选项…</p>}
          {current?.failed && <Button type="button" size="sm" variant="ghost"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              (activePicker ? searchRef.current : editorRef.current)?.focus()
              setRetryCount((count) => count + 1)
            }}>重试</Button>}
          {current && !current.failed && !items.length &&
            <p role="status" className="px-2 py-1 text-sm text-muted-foreground">没有匹配项</p>}
          <ul id={listId} ref={listRef} role="listbox" aria-label="候选项" className="relative max-h-52 overflow-auto">
            {items.map((candidate, index) => {
              const detail = [candidateKinds[candidate.kind], candidate.detail].filter(Boolean).join(' · ')
              return <li
                key={`${candidate.kind}:${candidate.id}`}
                id={`${listId}-${index}`}
                role="option"
                aria-label={`${candidate.label} ${detail}`}
                aria-selected={index === activeIndex}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent aria-selected:bg-accent"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => insert(candidate)}
              >
                {mode === 'image' && candidate.thumbnailUrl &&
                  <img src={candidate.thumbnailUrl} alt="" className="size-8 rounded object-cover" />}
                <span className="min-w-0 flex-1 truncate">{candidate.label}</span>
                <span className="max-w-2/5 shrink-0 truncate text-xs text-muted-foreground">
                  {detail}
                </span>
              </li>
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
