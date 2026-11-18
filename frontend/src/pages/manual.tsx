// 静态使用手册页面(REQ-5):直接消费静态内容模块,不调用后端接口、不使用 react-query。
import type { ReactNode } from 'react'
import { MANUAL_CHAPTERS } from '@/manual/content'

/** 行内 Markdown:**加粗** 与 `行内代码`;其余文本原样输出,不解析 HTML。 */
function renderInline(text: string, keyBase: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
    .filter((part) => part.length > 0)
    .map((part, index) => {
      const key = `${keyBase}-i${index}`
      if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
        return <strong key={key}>{part.slice(2, -2)}</strong>
      }
      if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
        return (
          <code key={key} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
            {part.slice(1, -1)}
          </code>
        )
      }
      return part
    })
}

function isTableDivider(line: string): boolean {
  return /^\|[\s:|-]+\|?$/.test(line)
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

const LINE_BLOCK_START = /^(#{2,4}\s|- |\d+\.\s|\|)/

/** 极简 Markdown 分块渲染:支持标题(##/###/####)、列表、表格、代码块与段落,覆盖手册内容的全部形态。 */
function renderBlocks(markdown: string): ReactNode[] {
  const lines = markdown.split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let blockIndex = 0
  const nextKey = () => `mb-${blockIndex++}`

  while (index < lines.length) {
    const trimmed = lines[index].trim()
    if (!trimmed) {
      index += 1
      continue
    }

    if (trimmed.startsWith('#### ')) {
      blocks.push(
        <h4 key={nextKey()} className="mt-4 mb-1 text-sm font-semibold">
          {renderInline(trimmed.slice(5), nextKey())}
        </h4>,
      )
      index += 1
      continue
    }
    if (trimmed.startsWith('### ')) {
      blocks.push(
        <h3 key={nextKey()} className="mt-5 mb-2 text-base font-semibold">
          {renderInline(trimmed.slice(4), nextKey())}
        </h3>,
      )
      index += 1
      continue
    }
    if (trimmed.startsWith('## ')) {
      blocks.push(
        <h3 key={nextKey()} className="mt-6 mb-2 text-lg font-semibold">
          {renderInline(trimmed.slice(3), nextKey())}
        </h3>,
      )
      index += 1
      continue
    }

    if (trimmed.startsWith('- ')) {
      const items: string[] = []
      while (index < lines.length && lines[index].trim().startsWith('- ')) {
        items.push(lines[index].trim().slice(2))
        index += 1
      }
      const listKey = nextKey()
      blocks.push(
        <ul key={listKey} className="my-2 list-disc space-y-1 pl-5">
          {items.map((item, itemIndex) => (
            <li key={`${listKey}-${itemIndex}`}>{renderInline(item, `${listKey}-${itemIndex}`)}</li>
          ))}
        </ul>,
      )
      continue
    }

    if (/^\d+\.\s/.test(trimmed)) {
      const items: string[] = []
      while (index < lines.length && /^\d+\.\s/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s/, ''))
        index += 1
      }
      const listKey = nextKey()
      blocks.push(
        <ol key={listKey} className="my-2 list-decimal space-y-1 pl-5">
          {items.map((item, itemIndex) => (
            <li key={`${listKey}-${itemIndex}`}>{renderInline(item, `${listKey}-${itemIndex}`)}</li>
          ))}
        </ol>,
      )
      continue
    }

    if (trimmed.startsWith('|')) {
      const rows: string[] = []
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        rows.push(lines[index].trim())
        index += 1
      }
      const header = parseTableRow(rows[0] ?? '')
      const bodyRows = rows
        .slice(1)
        .filter((row) => !isTableDivider(row))
        .map(parseTableRow)
      const tableKey = nextKey()
      blocks.push(
        <div key={tableKey} className="my-3 overflow-x-auto rounded-md border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-muted/50">
                {header.map((cell, cellIndex) => (
                  <th key={cellIndex} className="border px-3 py-1.5 text-left font-medium">
                    {renderInline(cell, `${tableKey}-h${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((cells, rowIndex) => (
                <tr key={rowIndex}>
                  {cells.map((cell, cellIndex) => (
                    <td key={cellIndex} className="border px-3 py-1.5 align-top">
                      {renderInline(cell, `${tableKey}-r${rowIndex}c${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    if (trimmed.startsWith('```')) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <pre key={nextKey()} className="my-3 overflow-x-auto rounded-md bg-muted p-3 text-sm">
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim() && !LINE_BLOCK_START.test(lines[index].trim())) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push(
      <p key={nextKey()} className="my-2 leading-relaxed">
        {renderInline(paragraph.join(' '), nextKey())}
      </p>,
    )
  }
  return blocks
}

export function ManualPage() {
  return (
    <div className="mx-auto w-full max-w-4xl pb-16">
      <header className="border-b pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">使用手册</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          静态使用手册,内容随产品版本更新;点击目录中的章节可快速定位到对应内容。
        </p>
      </header>
      <nav aria-label="手册目录" className="mt-6 rounded-lg border bg-muted/30 p-4">
        <ol className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
          {MANUAL_CHAPTERS.map((chapter, position) => (
            <li key={chapter.id}>
              <a href={`#${chapter.id}`} className="text-sm text-primary hover:underline">
                {position + 1}. {chapter.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <div className="mt-8 space-y-12">
        {MANUAL_CHAPTERS.map((chapter) => (
          <section key={chapter.id} id={chapter.id} className="scroll-mt-6">
            <h2 className="text-2xl font-semibold tracking-tight">{chapter.title}</h2>
            <div className="mt-1 wrap-anywhere text-sm">{renderBlocks(chapter.markdown)}</div>
          </section>
        ))}
      </div>
    </div>
  )
}
