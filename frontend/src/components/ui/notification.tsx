import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { CircleAlert, X } from 'lucide-react'

import { Button } from '@/components/ui/button'

type Notice = { id: number; message: string }

const NotificationContext = createContext<(message: string) => void>(() => undefined)

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])

  const notify = useCallback((message: string) => {
    setNotices((current) => {
      if (current.some((notice) => notice.message === message)) return current
      return [...current, { id: Date.now(), message }]
    })
  }, [])

  return (
    <NotificationContext.Provider value={notify}>
      {children}
      <div className="fixed right-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2" aria-live="polite">
        {notices.map((notice) => (
          <div
            key={notice.id}
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-background p-4 text-sm shadow-lg"
          >
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <p className="flex-1 text-foreground">{notice.message}</p>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="-mr-1 -mt-1 shrink-0"
              onClick={() => setNotices((current) => current.filter((item) => item.id !== notice.id))}
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
  const notify = useNotification()

  useEffect(() => {
    if (message) notify(message)
  }, [message, notify])

  return null
}
