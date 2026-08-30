import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { MANUAL_CHAPTERS } from './content'

// jsdom 环境的全局 URL 会把相对引用解析到文档地址,须用 node:url/node:path 做源码定位。
const HERE = dirname(fileURLToPath(import.meta.url))

// 需求 fdb2847c「静态使用手册」要求覆盖的全部主题;keywords 为章节标题中应同时出现的词。
const REQUIRED_TOPICS: Array<{ topic: string; keywords: string[] }> = [
  { topic: '登录与账号', keywords: ['登录'] },
  { topic: '项目与成员角色', keywords: ['项目', '角色'] },
  { topic: '需求/任务状态流转与看板', keywords: ['需求', '任务'] },
  { topic: '文档三模块(Wiki/词典/API)', keywords: ['文档'] },
  { topic: '记忆管理与蒸馏', keywords: ['记忆'] },
  { topic: '通知与搜索', keywords: ['通知', '搜索'] },
  { topic: 'Agent 与 API key', keywords: ['Agent'] },
  { topic: '权限矩阵', keywords: ['权限'] },
  { topic: '常见问题', keywords: ['常见问题'] },
]

function allMarkdown(): string {
  return MANUAL_CHAPTERS.map((chapter) => chapter.markdown).join('\n')
}

describe('使用手册内容完整性', () => {
  it('章节清单覆盖需求列出的全部主题', () => {
    expect(Array.isArray(MANUAL_CHAPTERS)).toBe(true)
    expect(MANUAL_CHAPTERS.length).toBeGreaterThanOrEqual(REQUIRED_TOPICS.length)
    const titles = MANUAL_CHAPTERS.map((chapter) => chapter.title)
    expect(new Set(titles).size).toBe(titles.length)
    for (const { topic, keywords } of REQUIRED_TOPICS) {
      const matched = titles.filter((title) => keywords.every((keyword) => title.includes(keyword)))
      expect(matched.length, `章节标题需覆盖主题「${topic}」;现有章节:${titles.join(' / ')}`).toBeGreaterThan(0)
    }
  })

  it('每章均有唯一锚点 id 与非空 Markdown 正文', () => {
    const ids = MANUAL_CHAPTERS.map((chapter) => chapter.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const chapter of MANUAL_CHAPTERS) {
      expect(chapter.id).toMatch(/^[a-z0-9-]+$/)
      expect(typeof chapter.markdown).toBe('string')
      expect(chapter.markdown.trim().length).toBeGreaterThan(20)
    }
  })

  it('状态词与前端功能需求 v1.0 定稿一致(需求五态/任务五态)', () => {
    const all = allMarkdown()
    // 需求五态:待确认/待办/实现中/已完成/已取消;任务五态:待办/实现中/验收中/已完成/已取消
    for (const term of ['待确认', '待办', '实现中', '验收中', '已完成', '已取消']) {
      expect(all).toContain(term)
    }
  })

  it('正文覆盖文档三模块、看板、蒸馏、API key 与权限矩阵角色', () => {
    const all = allMarkdown()
    for (const term of ['Wiki', '词典', 'API', '看板', '蒸馏', 'admin', 'owner', 'editor', 'viewer']) {
      expect(all).toContain(term)
    }
    expect(all).toMatch(/api key/i)
  })
})

describe('使用手册静态性守护', () => {
  it('内容模块存在且为随前端打包的静态资源,不含对 Zeichen Wiki API 的运行时依赖', () => {
    const contentSource = readFileSync(resolve(HERE, './content.ts'), 'utf-8')
    expect(contentSource).toContain('export const MANUAL_CHAPTERS')
    for (const banned of ["from '@/lib/api'", 'api.get', 'api.post', 'fetch(', '/documents/wiki', 'XMLHttpRequest']) {
      expect(contentSource.includes(banned), `内容模块不得包含运行时依赖:${banned}`).toBe(false)
    }
  })

  it('手册页面直接消费静态内容模块,不调用后端接口', () => {
    const pageSource = readFileSync(resolve(HERE, '../pages/manual.tsx'), 'utf-8')
    expect(pageSource).toContain('MANUAL_CHAPTERS')
    for (const banned of ["from '@/lib/api'", 'api.get', 'api.post', 'fetch(', '/documents/wiki', '@tanstack/react-query']) {
      expect(pageSource.includes(banned), `手册页面不得包含运行时后端依赖:${banned}`).toBe(false)
    }
  })
})
