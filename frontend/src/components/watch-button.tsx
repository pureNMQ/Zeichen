import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { api, withProject } from '@/lib/api'

// 实体级关注(REQ 023b607e):关注的实体变更始终通知,不受偏好收窄影响。
export function WatchButton({ targetType, targetId }: { targetType: string; targetId: string }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['watch', targetType, targetId],
    queryFn: () => api.get<{ watching: boolean }>(withProject(`/targets/${targetType}/${targetId}/watch`)),
  })
  const [busy, setBusy] = useState(false)
  const watching = data?.watching ?? false

  async function toggle() {
    setBusy(true)
    try {
      if (watching) await api.delete(withProject(`/targets/${targetType}/${targetId}/watch`))
      else await api.post(withProject(`/targets/${targetType}/${targetId}/watch`))
      await qc.invalidateQueries({ queryKey: ['watch', targetType, targetId] })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      className="h-7 text-xs"
      onClick={() => void toggle()}
      disabled={busy}
      aria-pressed={watching}
    >
      {watching ? '取消关注' : '关注'}
    </Button>
  )
}
