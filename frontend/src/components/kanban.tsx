import { DndContext, DragOverlay, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { useEffect, useState, type ReactNode } from 'react'

import { STATUS_LABEL, type WorkflowStatus } from '@/lib/api'
import { STATUS_DOT } from '@/components/status-badge'
import { cn } from '@/lib/utils'

export interface KanbanItem {
  id: string
  status: WorkflowStatus
}

const DEFAULT_COLUMNS: WorkflowStatus[] = ['backlog', 'in_progress', 'verifying', 'done', 'cancelled']

export function getEffectiveStatus(item: KanbanItem, overrides: Record<string, WorkflowStatus>): WorkflowStatus {
  return overrides[item.id] ?? item.status
}

export function pruneOverrides<T extends KanbanItem>(
  items: T[],
  overrides: Record<string, WorkflowStatus>,
): Record<string, WorkflowStatus> {
  const byId = new Map(items.map((i) => [i.id, i]))
  const pruned: Record<string, WorkflowStatus> = {}
  for (const [id, status] of Object.entries(overrides)) {
    const item = byId.get(id)
    if (item && item.status !== status) pruned[id] = status
  }
  return pruned
}

interface ColumnProps {
  status: WorkflowStatus
  canDrop: boolean
  isActiveTarget: boolean
  children: ReactNode
}

function Column({ status, canDrop, isActiveTarget, children }: ColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: status, disabled: !canDrop })
  const showPlaceholder = isOver && canDrop
  return (
    <div
      ref={setNodeRef}
      className={cn(
        'flex w-64 shrink-0 flex-col gap-2 rounded-lg border bg-muted/20 p-2',
        showPlaceholder && 'border-primary ring-1 ring-primary/40',
        !showPlaceholder && isActiveTarget && canDrop && 'border-dashed border-primary/60',
      )}
    >
      <div className="flex items-center gap-1.5 px-1 text-xs font-medium text-muted-foreground">
        <span className={cn('size-2 shrink-0 rounded-full', STATUS_DOT[status])} />
        {STATUS_LABEL[status]}
      </div>
      <div className="flex min-h-24 flex-col gap-2">
        {children}
        {showPlaceholder && (
          <div className="rounded-md border-2 border-dashed border-primary/50 p-3 text-center text-xs text-primary/60">
            松开放置
          </div>
        )}
      </div>
    </div>
  )
}

interface DraggableCardProps {
  id: string
  canDrag: boolean
  children: ReactNode
}

function DraggableCard({ id, canDrag, children }: DraggableCardProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id, disabled: !canDrag })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn(
        'cursor-grab touch-none',
        isDragging && 'opacity-30',
        !canDrag && 'cursor-default',
      )}
    >
      {children}
    </div>
  )
}

interface KanbanProps<T extends KanbanItem> {
  items: T[]
  canDrag: boolean
  renderCard: (item: T) => ReactNode
  onMove: (id: string, to: WorkflowStatus) => void
  columns?: WorkflowStatus[]
  className?: string
}

export function Kanban<T extends KanbanItem>({ items, canDrag, renderCard, onMove, columns = DEFAULT_COLUMNS, className }: KanbanProps<T>) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const [activeId, setActiveId] = useState<string | null>(null)
  const [overrides, setOverrides] = useState<Record<string, WorkflowStatus>>({})

  useEffect(() => {
    setOverrides((prev) => {
      const pruned = pruneOverrides(items, prev)
      return Object.keys(pruned).length === Object.keys(prev).length ? prev : pruned
    })
  }, [items])

  function handleDragStart(event: DragStartEvent) {
    setActiveId(String(event.active.id))
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveId(null)
    const id = String(event.active.id)
    const to = event.over?.id
    if (typeof to !== 'string' || !STATUS_LABEL[to as WorkflowStatus]) return
    const item = items.find((i) => i.id === id)
    if (!item || getEffectiveStatus(item, overrides) === to) return
    setOverrides((prev) => ({ ...prev, [id]: to as WorkflowStatus }))
    onMove(id, to as WorkflowStatus)
  }

  const activeItem = activeId ? items.find((i) => i.id === activeId) : null

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className="flex min-h-0 flex-1 items-start gap-3 overflow-x-auto pb-2">
          {columns.map((status) => (
            <Column key={status} status={status} canDrop={canDrag} isActiveTarget={!!activeItem}>
              {items
                .filter((i) => getEffectiveStatus(i, overrides) === status)
                .map((item) => (
                  <DraggableCard key={item.id} id={item.id} canDrag={canDrag}>
                    {renderCard(item)}
                  </DraggableCard>
                ))}
            </Column>
          ))}
        </div>
        <DragOverlay dropAnimation={{ duration: 120 }}>
          {activeItem ? <div className="w-64">{renderCard(activeItem)}</div> : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
