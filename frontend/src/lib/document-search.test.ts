import { describe, expect, it } from 'vitest'
import { filterNodesByTitle } from '@/lib/document-search'

// REQ-4 要点 3:文档树内搜索。契约:按标题过滤已加载的文档树节点,
// 大小写不敏感子串匹配;空串/纯空白返回全部;目录节点同样参与过滤。
type Node = { id: string; title: string; node_kind?: 'document' | 'directory' }

const nodes: Node[] = [
  { id: 'a', title: '部署 Runbook', node_kind: 'document' },
  { id: 'b', title: 'Deploy Runbook', node_kind: 'document' },
  { id: 'c', title: '需求梳理笔记', node_kind: 'document' },
  { id: 'd', title: '运维手册目录', node_kind: 'directory' },
]

describe('文档树按标题过滤(filterNodesByTitle)', () => {
  it('空串与纯空白查询返回全部节点并保持原顺序', () => {
    expect(filterNodesByTitle(nodes, '')).toEqual(nodes)
    expect(filterNodesByTitle(nodes, '   ')).toEqual(nodes)
  })

  it('按标题大小写不敏感子串匹配', () => {
    expect(filterNodesByTitle(nodes, 'runbook').map((node) => node.id)).toEqual(['a', 'b'])
    expect(filterNodesByTitle(nodes, 'RUNBOOK').map((node) => node.id)).toEqual(['a', 'b'])
    expect(filterNodesByTitle(nodes, 'deploy').map((node) => node.id)).toEqual(['b'])
    expect(filterNodesByTitle(nodes, '部署').map((node) => node.id)).toEqual(['a'])
  })

  it('目录节点同样参与标题过滤', () => {
    expect(filterNodesByTitle(nodes, '目录').map((node) => node.id)).toEqual(['d'])
  })

  it('查询词两侧空白被忽略', () => {
    expect(filterNodesByTitle(nodes, ' 需求梳理 ')).toEqual([nodes[2]])
  })

  it('无匹配时返回空数组', () => {
    expect(filterNodesByTitle(nodes, '不存在的标题')).toEqual([])
  })
})
