import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { STATUS_COLORS, STATUS_DOT } from '@/components/status-badge'
import { STATUS_LABEL, type WorkflowStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

export function StatusSelect({
  value,
  statuses,
  onSelect,
  disabled,
  ariaLabel = '状态',
  className,
}: {
  value: WorkflowStatus
  statuses: string[]
  onSelect: (s: string) => void
  disabled?: boolean
  ariaLabel?: string
  className?: string
}) {
  return (
    <Select value={value} onValueChange={onSelect} disabled={disabled}>
      <SelectTrigger
        size="sm"
        aria-label={ariaLabel}
        disabled={disabled}
        className={cn(
          'h-6 w-fit gap-1 border-transparent px-1.5 text-xs',
          STATUS_COLORS[value],
          className,
        )}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {statuses.map((s) => (
          <SelectItem key={s} value={s}>
            <span className="flex items-center gap-1.5">
              <span className={cn('size-2 shrink-0 rounded-full', STATUS_DOT[s as WorkflowStatus])} />
              {STATUS_LABEL[s as WorkflowStatus]}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
