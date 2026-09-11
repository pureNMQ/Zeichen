import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { api } from '@/lib/api'

const DOMAIN_LABELS: Record<string, string> = {
  requirement: '需求',
  task: '任务',
  document: '文档',
  project: '项目',
}

const ACTION_LABELS: Record<string, string> = {
  create: '创建',
  update: '更新',
  status: '变更状态',
  comment: '评论',
  reference: '引用',
  assign: '指派',
  claim: '认领',
  delete: '删除',
  restore: '恢复',
  move: '移动',
}

interface Prefs {
  domains: Record<string, boolean>
  actions: Record<string, boolean>
}

// 通知偏好(REQ 023b607e):按域/动作收窄通知;默认全开,仅关闭项生效。
export function NotificationPreferencesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['notification-preferences'],
    queryFn: () => api.get<Prefs>('/users/me/notification-preferences'),
    enabled: open,
  })
  const [domains, setDomains] = useState<Prefs['domains']>({})
  const [actions, setActions] = useState<Prefs['actions']>({})
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open && data) {
      setDomains(data.domains)
      setActions(data.actions)
      setError(null)
    }
  }, [open, data])

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await api.put('/users/me/notification-preferences', { domains, actions })
      await qc.invalidateQueries({ queryKey: ['notification-preferences'] })
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败,请重试')
    } finally {
      setSaving(false)
    }
  }

  function renderGroup(label: string, html_for_prefix: string, entries: [string, boolean][], toggle: (key: string, v: boolean) => void) {
    return (
      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium">{label}</legend>
        {entries.map(([key, enabled]) => (
          <label key={key} className="flex items-center gap-2 text-sm" htmlFor={`${html_for_prefix}-${key}`}>
            <input
              id={`${html_for_prefix}-${key}`}
              type="checkbox"
              checked={enabled}
              autoComplete="off"
              onChange={(e) => toggle(key, e.target.checked)}
            />
            {DOMAIN_LABELS[key] ?? ACTION_LABELS[key] ?? key}
          </label>
        ))}
      </fieldset>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>通知偏好</DialogTitle>
          <DialogDescription>关闭的域或动作不再推送通知;已关注实体不受影响。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          {renderGroup('按实体域', 'pref-domain', Object.entries(domains), (key, v) => setDomains({ ...domains, [key]: v }))}
          {renderGroup('按动作', 'pref-action', Object.entries(actions), (key, v) => setActions({ ...actions, [key]: v }))}
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={() => void save()} disabled={saving}>{saving ? '保存中…' : '保存'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
