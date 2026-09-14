import { describe, expect, it } from 'vitest'
import { pointerWithin } from '@dnd-kit/core'

import { planDocumentMove, ROOT_DROP_ID, rootZoneFirstPointerWithin } from './document-tree-dnd'
import type { CollisionDetection } from '@dnd-kit/core'

type CollisionArgs = Parameters<CollisionDetection>[0]

describe('planDocumentMove:拖放落点 → move 调用计划(REQ 73750031)', () => {
  it('Wiki 节点拖到另一 Wiki 上:作为其子文档', () => {
    expect(planDocumentMove('wiki', 'document', 'a1', 'document', 'b2')).toEqual({
      path: '/documents/wiki/a1/move',
      body: { parent_id: 'b2', directory_id: null },
    })
  })

  it('Wiki 节点拖到根级区:移回根级', () => {
    expect(planDocumentMove('wiki', 'document', 'a1', 'root', null)).toEqual({
      path: '/documents/wiki/a1/move',
      body: { parent_id: null, directory_id: null },
    })
  })

  it('拖到自身:无效(返回 null)', () => {
    expect(planDocumentMove('wiki', 'document', 'a1', 'document', 'a1')).toBeNull()
  })

  it('词典词条拖到目录上:归属该目录', () => {
    expect(planDocumentMove('glossary', 'document', 't1', 'directory', 'd1')).toEqual({
      path: '/documents/glossary/t1/move',
      body: { parent_id: null, directory_id: 'd1' },
    })
  })

  it('词典词条拖到根级区:移出目录', () => {
    expect(planDocumentMove('glossary', 'document', 't1', 'root', null)).toEqual({
      path: '/documents/glossary/t1/move',
      body: { parent_id: null, directory_id: null },
    })
  })

  it('词典词条拖到词条上:无效(词条不支持父文档)', () => {
    expect(planDocumentMove('glossary', 'document', 't1', 'document', 't2')).toBeNull()
  })

  it('目录拖到目录上:作为其子目录', () => {
    expect(planDocumentMove('glossary', 'directory', 'd1', 'directory', 'd2')).toEqual({
      path: '/directories/glossary/d1/move',
      body: { parent_id: 'd2' },
    })
  })

  it('目录拖到根级区:移回根级', () => {
    expect(planDocumentMove('glossary', 'directory', 'd1', 'root', null)).toEqual({
      path: '/directories/glossary/d1/move',
      body: { parent_id: null },
    })
  })
})

describe('rootZoneFirstPointerWithin:根级热区命中独占(TASK-112 打回修复)', () => {
  // 模拟 dnd-kit 传入:热区 sticky 悬浮,树行 row1 的矩形被热区几何覆盖
  const zoneRect = { left: 0, top: 0, right: 220, bottom: 40, width: 220, height: 40 }
  const rowRect = { left: 0, top: 4, right: 220, bottom: 32, width: 220, height: 28 }
  const args = (pointer: { x: number; y: number } | null, withZone = true): CollisionArgs =>
    ({
      pointerCoordinates: pointer,
      droppableRects: new Map([
        ...(withZone ? [[ROOT_DROP_ID, zoneRect] as const] : []),
        ['drop:document:row1', rowRect] as const,
      ]),
      droppableContainers: [
        ...(withZone ? [{ id: ROOT_DROP_ID }] : []),
        { id: 'drop:document:row1' },
      ],
    }) as unknown as CollisionArgs

  it('指针在热区内:只返回根级热区,不被下方树行抢占', () => {
    const collisions = rootZoneFirstPointerWithin(args({ x: 110, y: 20 }))
    expect(collisions).toHaveLength(1)
    expect(collisions[0].id).toBe(ROOT_DROP_ID)
  })

  it('指针在热区外的树行上:回落 pointerWithin 正常命中', () => {
    const pointer = { x: 110, y: 60 }
    expect(rootZoneFirstPointerWithin(args(pointer))).toEqual(pointerWithin(args(pointer)))
  })

  it('指针为空(键盘拖拽等):不命中热区,回落 pointerWithin', () => {
    expect(rootZoneFirstPointerWithin(args(null))).toEqual([])
  })

  it('热区未注册(无编辑权):不命中热区,回落 pointerWithin', () => {
    expect(rootZoneFirstPointerWithin(args({ x: 110, y: 20 }, false))).toEqual(
      pointerWithin(args({ x: 110, y: 20 }, false))
    )
  })
})
