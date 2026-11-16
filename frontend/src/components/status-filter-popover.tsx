import { Popover as PopoverPrimitive } from 'radix-ui'
import { SlidersHorizontal } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { STATUS_LABEL, type WorkflowStatus } from '@/lib/api'

/** 状态多选筛选:按钮打开弹层,五态(或任务五态)checkbox 多选 */
export function StatusFilterPopover({
  statuses,
  value,
  onChange,
}: {
  statuses: string[]
  value: string[]
  onChange: (next: string[]) => void
}) {
  function toggle(status: string) {
    onChange(value.includes(status) ? value.filter((s) => s !== status) : [...value, status])
  }

  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>
        <Button variant="outline" size="sm" aria-label="状态">
          <SlidersHorizontal className="h-4 w-4" />
          状态
        </Button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="start"
          sideOffset={4}
          className="z-50 min-w-40 rounded-lg bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          <div className="space-y-1">
            {statuses.map((status) => (
              <div key={status} className="flex items-center gap-2 rounded-md px-1 py-0.5">
                <input
                  type="checkbox"
                  id={`status-filter-${status}`}
                  checked={value.includes(status)}
                  onChange={() => toggle(status)}
                  autoComplete="off"
                  className="size-4 accent-primary"
                />
                <Label htmlFor={`status-filter-${status}`}>
                  {STATUS_LABEL[status as WorkflowStatus]}
                </Label>
              </div>
            ))}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
