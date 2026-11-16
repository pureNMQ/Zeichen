import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

// 两套配色联动抽查(REQ-6):防止「只改壳不改里」。
// - 基线:index.css 具备 :root 与 .dark 双变量块,dark: 变体基于 .dark 类(类切换,非媒体查询)
// - 抽查 1:关键组件(状态徽章)在 .dark 下有显式适配
// - 抽查 2:全站非测试源码不得存在「未配 dark: 变体」的硬编码调色板色类;
//   要么补 dark: 配对,要么改用语义 token(bg-background/text-muted-foreground 等)。
//   若个别用法经 token 定稿裁决为明暗通用色,可在 EXEMPT_FILES 中显式豁免并注明理由。

// vitest 以 frontend/ 为工作目录运行(npm test);兼容从仓库根目录运行的情况
const SRC_ROOT = existsSync(resolve(process.cwd(), 'src', 'index.css'))
  ? join(process.cwd(), 'src')
  : join(process.cwd(), 'frontend', 'src')

function listSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (name === 'node_modules' || name === 'test') continue
    if (/\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) {
      out.push(full)
    }
  }
  // readdirSync 不递归子目录,这里手动递归
  for (const name of readdirSync(dir, { withFileTypes: true })) {
    if (name.isDirectory() && name.name !== 'node_modules' && name.name !== 'test') {
      out.push(...listSourceFiles(join(dir, name.name)))
    }
  }
  return out
}

// 经定稿裁决为明暗通用的硬编码色白名单(路径相对 src/),默认为空
const EXEMPT_FILES: string[] = []

const PALETTE_CLASS =
  /\b(bg|text|border|ring|fill|stroke|from|via|to)-(white|black|gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(-\d{1,3})?(\/\d{1,3})?\b/

describe('双色板基线(index.css)', () => {
  const css = readFileSync(join(SRC_ROOT, 'index.css'), 'utf-8')

  it('dark: 变体基于 .dark 类切换(非 prefers-color-scheme 媒体查询)', () => {
    expect(css).toContain('@custom-variant dark')
    expect(css).toMatch(/@custom-variant dark[^\n]*\.dark/)
  })

  it(':root 与 .dark 双变量块齐备,关键变量两套配色均定义', () => {
    const rootBlock = css.match(/:root\s*\{([^}]*)\}/)?.[1] ?? ''
    const darkBlock = css.match(/\.dark\s*\{([^}]*)\}/)?.[1] ?? ''
    expect(rootBlock).not.toBe('')
    expect(darkBlock).not.toBe('')
    const keyVars = ['--background', '--foreground', '--primary', '--border', '--card', '--muted', '--accent']
    for (const v of keyVars) {
      expect(rootBlock).toContain(`${v}:`)
      expect(darkBlock).toContain(`${v}:`)
    }
  })
})

describe('两套配色联动抽查', () => {
  it('关键组件抽查:状态徽章配色在 .dark 下有显式 dark: 适配', async () => {
    const { STATUS_COLORS } = await import('@/components/status-badge')
    for (const status of ['pending', 'in_progress', 'verifying', 'done'] as const) {
      expect(STATUS_COLORS[status], `状态 ${status} 缺少 dark: 适配`).toContain('dark:')
    }
  })

  it('全站无非测试源码中未配 dark: 的硬编码调色板色类', () => {
    const violations: string[] = []
    for (const file of listSourceFiles(SRC_ROOT)) {
      const rel = file.slice(SRC_ROOT.length).replace(/^\//, '')
      if (EXEMPT_FILES.includes(rel)) continue
      const lines = readFileSync(file, 'utf-8').split('\n')
      lines.forEach((line, i) => {
        if (PALETTE_CLASS.test(line) && !line.includes('dark:')) {
          violations.push(`${rel}:${i + 1}: ${line.trim().slice(0, 140)}`)
        }
      })
    }
    expect(violations).toEqual([])
  })
})
