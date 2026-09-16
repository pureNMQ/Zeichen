import { beforeEach, expect, it, describe } from 'vitest'

import { withProject } from '@/lib/api'

// REQ-55:全局短码端点附带 project_id 消歧;显式 projectId 优先,回退当前项目(localStorage)
describe('withProject(短码跨项目消歧)', () => {
  beforeEach(() => localStorage.clear())

  it('无当前项目时路径原样返回', () => {
    expect(withProject('/tasks/TASK-1')).toBe('/tasks/TASK-1')
  })

  it('回退当前项目:已带查询串用 & 连接', () => {
    localStorage.setItem('zeichen.currentProjectId', 'p-1')
    expect(withProject('/requirements/REQ-1/status')).toBe('/requirements/REQ-1/status?project_id=p-1')
    expect(withProject('/targets/requirement/REQ-1/comments?limit=50')).toBe(
      '/targets/requirement/REQ-1/comments?limit=50&project_id=p-1',
    )
  })

  it('显式 projectId 优先于当前项目', () => {
    localStorage.setItem('zeichen.currentProjectId', 'p-1')
    expect(withProject('/tasks/TASK-1', 'p-2')).toBe('/tasks/TASK-1?project_id=p-2')
  })

  it('显式 projectId 为空时回退当前项目', () => {
    localStorage.setItem('zeichen.currentProjectId', 'p-1')
    expect(withProject('/tasks/TASK-1', null)).toBe('/tasks/TASK-1?project_id=p-1')
  })
})
