// REQ-4 要点 3:文档树内搜索通用原语。按标题对已加载的树节点做
// 大小写不敏感子串过滤;空串/纯空白查询返回全部;目录节点同样参与匹配。
// Wiki 与词典共用(需求 1dbe56db 在此基础上细化)。

export interface TitleSearchableNode {
  title: string
}

export function filterNodesByTitle<T extends TitleSearchableNode>(nodes: T[], query: string): T[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return nodes
  return nodes.filter((node) => node.title.toLowerCase().includes(needle))
}
