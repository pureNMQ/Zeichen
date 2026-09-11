import { describe, expect, it } from 'vitest'

import { planDocumentMove } from './document-tree-dnd'

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
