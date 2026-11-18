import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationProvider } from '@/components/ui/notification'
import { RequirementDependencies } from '@/components/requirement-dependencies'
import { WorkHistory } from '@/components/work-history'
import { api, ApiError, type RequirementRow } from '@/lib/api'
import { associateProjectFile } from '@/lib/project-files'
import { WorkEditorPage } from './work-editor'

vi.mock('@/lib/api', async original => ({ ...(await original<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() },
}))
vi.mock('@/lib/current-project', () => ({ useProjectRole: () => 'editor' }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 'writer' } }) }))
vi.mock('@/lib/project-files', async original => ({ ...(await original<typeof import('@/lib/project-files')>()),
  associateProjectFile: vi.fn(),
}))
vi.mock('@/components/vditor-ir-editor', async () => ({
  WysiwygMarkdownEditor: (await import('@/test/fake-wysiwyg-editor')).FakeWysiwygMarkdownEditor,
  VditorMarkdownViewer: ({markdown}:{markdown:string}) => <article>{markdown}</article> }))
const item: RequirementRow = {
  id: 'REQ-12', project_id: 'p', title: '邀请成员', description:'原始内容', version:1,
  status:'in_progress', task_count:0, created_at:'', updated_at:'', created_by:'writer',
}
function show(path: string, body: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry:false } } })
  return render(<QueryClientProvider client={client}><NotificationProvider>
    <MemoryRouter initialEntries={[path]}>{body}</MemoryRouter>
  </NotificationProvider></QueryClientProvider>)
}
beforeEach(() => { vi.resetAllMocks(); localStorage.clear() })
describe('需求编辑与恢复', () => {
  it('并发保存保留草稿，用户核对后才改用最新版本', async () => {
    let current = item
    vi.mocked(api.get).mockImplementation(async () => current)
    vi.mocked(api.patch).mockImplementationOnce(async () => {
      current = { ...item, version:2, description:'其他人的修改' }
      throw new ApiError(409,'版本冲突')
    }).mockResolvedValue({...item,version:3})
    show('/projects/p/requirements/REQ-12/edit', <Routes>
      <Route path="/projects/:projectId/requirements/:id/edit" element={<WorkEditorPage kind="requirements" />} />
      <Route path="/projects/:projectId/requirements/:id" element={<>已保存</>} />
    </Routes>)
    const user = userEvent.setup()
    const editor = await screen.findByRole('textbox',{name:'正文'})
    await user.type(editor,'我的修改')
    await user.click(screen.getByRole('button',{name:'保存'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('草稿已保留')
    expect(editor).toHaveTextContent('原始内容')
    expect(editor).toHaveTextContent('我的修改')
    expect(vi.mocked(api.patch).mock.calls[0][1]).toMatchObject({description: editor.textContent})
    await user.click(await screen.findByRole('button',{name:'已核对，基于当前版本继续'}))
    await user.click(screen.getByRole('button',{name:'保存'}))
    expect(await screen.findByText('已保存')).toBeVisible()
    expect(vi.mocked(api.patch).mock.calls.map(c => (c[1] as {expected_version:number}).expected_version)).toEqual([1,2])
  })
  it('从具体版本的链接阅读、对照当前正文并带版本号恢复', async () => {
    const path = '/projects/p/requirements/REQ-12/versions'
    const first = {version:1,title:'旧标题',description:'早期说明',created_at:'2026-01-01',actor_id:'agent',actor_name:'校对助手',actor_is_agent:true}
    const older = {...first,version:2,actor_id:null,actor_name:null,actor_is_agent:null}
    const current = {...first,version:3,actor_id:'human',actor_name:'林舟',actor_is_agent:false}
    vi.mocked(api.get).mockImplementation(async endpoint => endpoint === path ? {items:[current,older,first],next_before:null} : first)
    show('/?version=1', <WorkHistory item={{...item,version:3}} projectId="p" kind="requirements" canEdit />)
    const user = userEvent.setup()
    expect(await screen.findByText('早期说明')).toBeVisible()
    expect(screen.getByText('v1 · 校对助手（Agent）', {selector:'p'})).toBeVisible()
    expect(screen.getByRole('option',{name:/v2 · 作者未记录/})).toBeInTheDocument()
    expect(screen.getByRole('option',{name:/v3 · 林舟/})).toBeInTheDocument()
    await user.click(screen.getByRole('button',{name:'对照当前版本'}))
    expect(screen.getByText('原始内容')).toBeVisible()
    expect(screen.getByText('当前 · v3 · 林舟')).toBeVisible()
    await user.click(screen.getByRole('button',{name:'恢复此版本'}))
    expect(api.post).toHaveBeenCalledWith(path+'/1/restore',{expected_version:3})
  })
  it('需求层显示双向依赖和解除状态，可解除前置关联', async () => {
    vi.mocked(api.get).mockResolvedValue({items:[], next_cursor:null})
    show('/', <RequirementDependencies canEdit item={{...item,blocked_by:[{id:'REQ-3',title:'名册',status:'done'}],
      blocks:[{id:'REQ-15',title:'入组验收',status:'backlog'}]}} />)
    const user = userEvent.setup()
    expect(screen.getByText('已完成')).toBeVisible()
    expect(screen.getByRole('link',{name:/入组验收/})).toHaveAttribute('href','/projects/p/requirements/REQ-15')
    await user.click(screen.getByRole('button',{name:'管理前置需求'}))
    await user.click(screen.getByRole('button',{name:'移除前置需求 REQ-3'}))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/requirements/REQ-12?project_id=p',{blocked_by:[],expected_blocked_by:['REQ-3']}))
  })
  it('恢复提交期间切换任务面板，迟到的回执不改动地址', async () => {
    let finish!: () => void
    vi.mocked(api.post).mockReturnValue(new Promise<void>(resolve => {finish=resolve}))
    const version = {version:1,title:'旧标题',created_at:'2026-11-19'}
    vi.mocked(api.get).mockImplementation(async path => path.endsWith('/versions') ? {items:[version]} : version)
    function Content() {
      const loc = useLocation()
      return <><Link to="?tab=tasks">任务</Link>{loc.search.includes('version=')
        ? <WorkHistory item={{...item,version:2}} projectId="p" kind="requirements" canEdit />
        : <output>{loc.search}</output>}</>
    }
    show('/?version=1', <Content />)
    const user = userEvent.setup()
    const restore = await screen.findByRole('button',{name:'恢复此版本'})
    await user.dblClick(restore)
    expect(api.post).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('link',{name:'任务'}))
    await act(async () => finish())
    expect(screen.getByText('?tab=tasks')).toBeVisible()
    expect(screen.queryByLabelText('历史版本')).toBeNull()
  })

  const createForm = <Routes>
      <Route path="/projects/:projectId/requirements/new" element={<WorkEditorPage kind="requirements" creating />} />
      <Route path="/projects/:projectId/requirements/:id" element={<>创建完成</>} />
    </Routes>
  const createPath = '/projects/p/requirements/new'
  it('编辑页只显示正文上传，刷新后重放同一创建请求', async () => {
    const page = show(createPath, createForm)
    const user = userEvent.setup()
    vi.mocked(api.post).mockRejectedValueOnce(new Error('回执未收到')).mockResolvedValue(item)
    await user.type(screen.getByRole('textbox',{name:'标题'}),'邀请成员')
    expect(screen.queryByLabelText('附加文件')).toBeNull()
    expect(screen.getByRole('button',{name:'上传文件'})).toBeVisible()
    await user.click(screen.getByRole('button',{name:'保存'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('回执未收到')
    page.unmount()
    show(createPath, createForm)
    await user.click(screen.getByRole('button',{name:'确认创建结果'}))
    expect(await screen.findByText('创建完成')).toBeVisible()
    expect(vi.mocked(api.post).mock.calls[1]).toEqual(vi.mocked(api.post).mock.calls[0])
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({title:item.title,request_id:expect.any(String)})
    expect(associateProjectFile).not.toHaveBeenCalled()
  })
  it('恢复旧版草稿中已上传的附件，部分失败后只重试剩余关联', async () => {
    localStorage.setItem('zeichen.work-draft:writer:p::requirements:new:receipt', JSON.stringify({
      id: null, requestId: 'old-request-id', title: item.title, description: item.description,
      attachments: [{ id: 'a.txt', name: 'a.txt' }, { id: 'b.txt', name: 'b.txt' }],
    }))
    vi.mocked(api.post).mockResolvedValue(item)
    vi.mocked(associateProjectFile).mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('关联中断')).mockResolvedValue(undefined)
    const page = show(createPath, createForm)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button',{name:'确认创建结果'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('正文已保存')
    page.unmount()
    show(createPath, createForm)
    expect(screen.queryByText('a.txt')).toBeNull()
    expect(screen.getByText('b.txt')).toBeVisible()
    await user.click(screen.getByRole('button',{name:'继续保存'}))
    expect(await screen.findByText('创建完成')).toBeVisible()
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith('/projects/p/requirements', expect.objectContaining({request_id:'old-request-id'}))
    expect(vi.mocked(associateProjectFile).mock.calls.map(c => c[3])).toEqual(['a.txt','b.txt','b.txt'])
  })
})
