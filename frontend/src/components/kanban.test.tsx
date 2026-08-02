import { describe, expect, it } from 'vitest'

import { getEffectiveStatus, pruneOverrides, type KanbanItem } from '@/components/kanban'

const item = (id: string, status: KanbanItem['status']): KanbanItem => ({ id, status })

describe('getEffectiveStatus(乐观覆盖下的有效状态)', () => {
  it('无覆盖时返回服务端状态', () => {
    expect(getEffectiveStatus(item('t1', 'backlog'), {})).toBe('backlog')
  })

  it('有覆盖时返回覆盖状态', () => {
    expect(getEffectiveStatus(item('t1', 'backlog'), { t1: 'done' })).toBe('done')
  })

  it('覆盖不影响其他卡片', () => {
    expect(getEffectiveStatus(item('t2', 'in_progress'), { t1: 'done' })).toBe('in_progress')
  })
})

describe('pruneOverrides(服务端数据同步后的清理)', () => {
  const items = [item('t1', 'done'), item('t2', 'in_progress')]

  it('服务端状态已等于覆盖值时删除覆盖', () => {
    expect(pruneOverrides(items, { t1: 'done' })).toEqual({})
  })

  it('服务端状态未同步时保留覆盖', () => {
    expect(pruneOverrides(items, { t1: 'cancelled' })).toEqual({ t1: 'cancelled' })
  })

  it('卡片已不在列表中时删除覆盖(失败回滚/删除后清理)', () => {
    expect(pruneOverrides([items[0]], { t1: 'done', t2: 'done' })).toEqual({})
  })

  it('混合场景:已同步的删除、未同步的保留', () => {
    expect(pruneOverrides(items, { t1: 'done', t2: 'done' })).toEqual({ t2: 'done' })
  })
})
