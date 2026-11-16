import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

// 设计 token 定稿文档契约(REQ-6 视觉样式模板定稿):
// - 仓库内须存在定稿文档,推荐 frontend/design-tokens.md(或 docs/ 目录)
// - 文档须覆盖四维:色彩 / 字体 / 圆角 / 密度
// - 文档须记载两套配色(浅色/暗色),与明暗主题切换联动
// - 关键 token 与代码双向一致(抽查):CSS 变量在 index.css 定义,且被文档记载;字体与 --font-sans 一致

// vitest 以 frontend/ 为工作目录运行(npm test);兼容从仓库根目录运行的情况
const FRONTEND_ROOT = existsSync(resolve(process.cwd(), 'src', 'index.css'))
  ? process.cwd()
  : join(process.cwd(), 'frontend')
const REPO_ROOT = resolve(FRONTEND_ROOT, '..')

const DOC_DIRS = [
  { dir: FRONTEND_ROOT, label: 'frontend/' },
  { dir: join(FRONTEND_ROOT, 'docs'), label: 'frontend/docs/' },
  { dir: join(REPO_ROOT, 'docs'), label: 'docs/' },
]

function findTokenDoc(): string | null {
  for (const { dir } of DOC_DIRS) {
    if (!existsSync(dir)) continue
    for (const name of readdirSync(dir)) {
      if (/^design-token.*\.md$/.test(name)) return join(dir, name)
    }
  }
  return null
}

function readTokenDoc(): { path: string; content: string } | null {
  const path = findTokenDoc()
  return path ? { path, content: readFileSync(path, 'utf-8') } : null
}

describe('设计 token 定稿文档', () => {
  it('token 定稿文档存在(仓库内 design-token*.md)', () => {
    const doc = readTokenDoc()
    expect(doc, '缺少设计 token 定稿文档;期望位于 frontend/design-tokens.md 或 docs/ 下').toBeTruthy()
  })

  it('文档覆盖四维:色彩 / 字体 / 圆角 / 密度', () => {
    const doc = readTokenDoc()
    expect(doc).toBeTruthy()
    const content = doc!.content
    for (const dimension of ['色彩', '字体', '圆角', '密度']) {
      expect(content).toContain(dimension)
    }
  })

  it('文档记载两套配色(浅色与暗色),与明暗主题联动', () => {
    const doc = readTokenDoc()
    expect(doc).toBeTruthy()
    const content = doc!.content
    expect(content).toMatch(/浅色|light/i)
    expect(content).toMatch(/暗色|深色|dark/i)
  })
})

describe('token 文档与代码一致(抽查)', () => {
  const KEY_VARIABLES = ['--background', '--foreground', '--primary', '--border', '--radius']

  it('关键 CSS 变量在 index.css 中定义,且被定稿文档记载', () => {
    const doc = readTokenDoc()
    expect(doc).toBeTruthy()
    const css = readFileSync(join(FRONTEND_ROOT, 'src', 'index.css'), 'utf-8')
    for (const v of KEY_VARIABLES) {
      expect(css).toContain(v)
      expect(doc!.content).toContain(v)
    }
  })

  it('字体 token 一致:文档字体与 index.css --font-sans(Geist)一致', () => {
    const doc = readTokenDoc()
    expect(doc).toBeTruthy()
    const css = readFileSync(join(FRONTEND_ROOT, 'src', 'index.css'), 'utf-8')
    expect(css).toContain("--font-sans: 'Geist Variable'")
    expect(doc!.content).toContain('Geist')
  })
})
