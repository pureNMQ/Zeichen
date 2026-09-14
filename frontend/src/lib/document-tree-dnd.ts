// 文档树拖拽换父(REQ 73750031):把「拖拽节点 × 落点」翻译为 move API 调用。
// 规则与后端 _validate_location 对齐:
//   Wiki:可挂任意 Wiki 之下或移回根级;词条/目录类落点对 Wiki 无效。
//   词典词条:仅支持在根级与目录之间移动(不支持父文档)。
//   目录:可挂其他目录之下或移回根级。
// 循环/自引用等剩余校验由后端兜底,前端只拦截显而易见的无效组合。

import { pointerWithin, type Collision, type CollisionDetection } from '@dnd-kit/core'

export type TreeModule = 'wiki' | 'glossary'
export type DragKind = 'document' | 'directory'
export type DropTarget = { kind: DragKind | 'root'; id: string | null }

export const ROOT_DROP_ID = 'drop:root'

// 根级投放热区 sticky 悬浮于树行之上,指针进入热区时其几何矩形会同时覆盖下方树行;
// pointerWithin 按指针到矩形四角的平均距离排序,更矮的树行会排在更高的热区之前,
// 导致「投到热区却落到下方节点」。故热区命中时直接独占,其余情况回落 pointerWithin。
export const rootZoneFirstPointerWithin: CollisionDetection = (args) => {
  const zoneRect = args.droppableRects.get(ROOT_DROP_ID)
  const pointer = args.pointerCoordinates
  if (
    zoneRect &&
    pointer &&
    pointer.x >= zoneRect.left && pointer.x <= zoneRect.right &&
    pointer.y >= zoneRect.top && pointer.y <= zoneRect.bottom
  ) {
    const zoneContainer = args.droppableContainers.find((container) => container.id === ROOT_DROP_ID)
    if (zoneContainer) return [{ id: ROOT_DROP_ID, data: { droppableContainer: zoneContainer, value: 0 } } satisfies Collision]
  }
  return pointerWithin(args)
}

export interface MovePlan {
  path: string
  body: Record<string, unknown>
}

export function planDocumentMove(
  module: TreeModule,
  dragKind: DragKind,
  dragId: string,
  dropKind: DropTarget['kind'],
  dropId: string | null,
): MovePlan | null {
  if (dropKind === 'root') {
    if (dragKind === 'document') {
      return { path: `/documents/${module}/${dragId}/move`, body: { parent_id: null, directory_id: null } }
    }
    return { path: `/directories/${module}/${dragId}/move`, body: { parent_id: null } }
  }
  if (dropId === dragId) return null
  if (dragKind === 'document' && module === 'wiki' && dropKind === 'document') {
    return { path: `/documents/${module}/${dragId}/move`, body: { parent_id: dropId, directory_id: null } }
  }
  if (dragKind === 'document' && module === 'glossary' && dropKind === 'directory') {
    return { path: `/documents/${module}/${dragId}/move`, body: { parent_id: null, directory_id: dropId } }
  }
  if (dragKind === 'directory' && dropKind === 'directory') {
    return { path: `/directories/${module}/${dragId}/move`, body: { parent_id: dropId } }
  }
  return null
}
