import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { CheckCircle2, CircleAlert, X } from 'lucide-react'

import { Button } from '@/components/ui/button'

type Notice = { id: number; message: string; variant: 'error' | 'success' }
type NoticeVariant = Notice['variant']
type NotificationContextValue = {
  dismiss: (id: number) => void
  notify: (message: string, variant?: NoticeVariant) => number
}

const NotificationContext = createContext<NotificationContextValue>({
  dismiss: () => undefined,
  notify: () => 0,
})

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])
  const nextNoticeId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setNotices((current) => current.filter((notice) => notice.id !== id))
  }, [])

  const notify = useCallback((message: string, variant: NoticeVariant = 'error') => {
    const id = nextNoticeId.current++
    setNotices((current) => [...current, { id, message, variant }])
    return id
  }, [])

  return (
    <NotificationContext.Provider value={{ dismiss, notify }}>
      {children}
      <div className="fixed right-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2" aria-live="polite">
        {notices.map((notice) => (
          <div
            key={notice.id}
            role="alert"
            className={`flex items-start gap-3 rounded-lg border bg-background p-4 text-sm shadow-lg ${notice.variant === 'success' ? 'border-emerald-500/30' : 'border-destructive/30'}`}
          >
            {notice.variant === 'success'
              ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
            <p className="flex-1 text-foreground">{notice.message}</p>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="-mr-1 -mt-1 shrink-0"
              onClick={() => dismiss(notice.id)}
              aria-label="关闭提示"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  )
}

export function useNotification() {
  return useContext(NotificationContext)
}

export function ErrorNotification({ message }: { message: string | null | undefined }) {
  const { dismiss, notify } = useNotification()

  useEffect(() => {
    if (!message) return
    const id = notify(message)
    return () => dismiss(id)
  }, [dismiss, message, notify])

  return null
}
