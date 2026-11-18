import { useLayoutEffect, useMemo } from 'react'
import { useLocation } from 'react-router-dom'

/** Capture this navigation so an async action cannot redirect a later page. */
export function useCurrentPage() {
  const { key } = useLocation()
  const visit = useMemo(() => ({ active: false }), [key])
  useLayoutEffect(() => {
    visit.active = true
    return () => { visit.active = false }
  }, [visit])
  return () => visit.active
}
