import { Badge } from '@/components/ui/badge'
import { STATUS_LABEL, type WorkflowStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

export const STATUS_COLORS: Record<WorkflowStatus, string> = {
  backlog: 'border-transparent bg-muted text-muted-foreground',
  in_progress: 'border-transparent bg-blue-500/10 text-blue-600 dark:bg-blue-500/15 dark:text-blue-400',
  verifying: 'border-transparent bg-amber-500/10 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400',
  done: 'border-transparent bg-green-500/10 text-green-600 dark:bg-green-500/15 dark:text-green-400',
  cancelled: 'border-transparent bg-destructive/10 text-destructive dark:bg-destructive/20',
}

export const STATUS_DOT: Record<WorkflowStatus, string> = {
  backlog: 'bg-muted-foreground/60',
  in_progress: 'bg-blue-500',
  verifying: 'bg-amber-500',
  done: 'bg-green-500',
  cancelled: 'bg-destructive',
}

export function StatusBadge({ status, className }: { status: WorkflowStatus; className?: string }) {
  return (
    <Badge className={cn(STATUS_COLORS[status], className)}>{STATUS_LABEL[status]}</Badge>
  )
}
