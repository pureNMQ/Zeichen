import { createContext, useCallback, useContext, useRef, type ReactNode } from 'react'

type NavigationBlocker = (target: string) => boolean
type DocumentNavigationContextValue = {
  registerBlocker: (blocker: NavigationBlocker | null) => void
  requestNavigation: (target: string) => boolean
}

const DocumentNavigationContext = createContext<DocumentNavigationContextValue>({
  registerBlocker: (_blocker: NavigationBlocker | null) => undefined,
  requestNavigation: (_target: string) => false,
})

export function DocumentNavigationProvider({ children }: { children: ReactNode }) {
  const blockerRef = useRef<NavigationBlocker | null>(null)

  const registerBlocker = useCallback((blocker: NavigationBlocker | null) => {
    blockerRef.current = blocker
  }, [])

  const requestNavigation = useCallback((target: string) => blockerRef.current?.(target) ?? false, [])

  return (
    <DocumentNavigationContext.Provider value={{ registerBlocker, requestNavigation }}>
      {children}
    </DocumentNavigationContext.Provider>
  )
}

export function useDocumentNavigation() {
  return useContext(DocumentNavigationContext)
}
