import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { api, type TaskRow } from '@/lib/api'

// 任务引用链接:任务无独立页面(ADR 0003),解析所属需求后跳需求详情并定位任务弹窗。
// 解析失败(任务已删/不可见)退化为纯文本。

export function TaskRefLink({ taskId, children }: { taskId: string; children: ReactNode }) {
  const [href, setHref] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<TaskRow>(`/tasks/${taskId}`)
      .then((t) => {
        if (!cancelled && t.requirement_id) {
          setHref(`/requirements/${t.requirement_id}?task=${taskId}`)
        }
      })
      .catch(() => {
        // 任务不存在或不可见:保持纯文本
      })
    return () => {
      cancelled = true
    }
  }, [taskId])

  if (!href) return <span>{children}</span>
  return (
    <Link to={href} className="text-primary hover:underline">
      {children}
    </Link>
  )
}
