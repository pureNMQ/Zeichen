import { Badge } from '@/components/ui/badge'
import { STATUS_LABEL, type WorkflowStatus } from '@/lib/api'

const STATUS_VARIANT: Record<WorkflowStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  backlog: 'outline',
  in_progress: 'secondary',
  verifying: 'default',
  done: 'outline',
  cancelled: 'destructive',
}

export function StatusBadge({ status }: { status: WorkflowStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>
}
