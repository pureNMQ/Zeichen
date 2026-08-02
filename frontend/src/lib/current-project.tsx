import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type ProjectRole, type ProjectRow } from './api'

const STORAGE_KEY = 'zeichen.currentProjectId'

interface CurrentProjectContextValue {
  projects: ProjectRow[]
  isLoading: boolean
  currentProject: ProjectRow | null
  projectId: string | null
  role: ProjectRole | null
  selectProject: (id: string) => void
}

const CurrentProjectContext = createContext<CurrentProjectContextValue | null>(null)

export function CurrentProjectProvider({ children }: { children: ReactNode }) {
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<ProjectRow[]>('/projects'),
  })
  const [currentId, setCurrentId] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  )

  useEffect(() => {
    if (isLoading) return
    if (projects.length === 0) {
      if (currentId !== null) setCurrentId(null)
      return
    }
    if (currentId !== null && projects.some((p) => p.id === currentId)) {
      localStorage.setItem(STORAGE_KEY, currentId)
      return
    }
    setCurrentId(projects[0].id)
  }, [isLoading, projects, currentId])

  const currentProject = projects.find((p) => p.id === currentId) ?? null

  const selectProject = useCallback((id: string) => {
    setCurrentId(id)
  }, [])

  const value = useMemo<CurrentProjectContextValue>(
    () => ({
      projects,
      isLoading,
      currentProject,
      projectId: currentProject?.id ?? null,
      role: currentProject?.my_role ?? null,
      selectProject,
    }),
    [projects, isLoading, currentProject, selectProject],
  )

  return <CurrentProjectContext.Provider value={value}>{children}</CurrentProjectContext.Provider>
}

export function useCurrentProject(): CurrentProjectContextValue {
  const ctx = useContext(CurrentProjectContext)
  if (!ctx) throw new Error('useCurrentProject 必须在 CurrentProjectProvider 内使用')
  return ctx
}

export function useProjectRole(): ProjectRole | null {
  return useCurrentProject().role
}
