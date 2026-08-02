# 03 需求/任务闭环(后端 API + MCP + Web)

Status: resolved
Type: task
Blocked by: 02

## Question

实现需求与任务域完整闭环(规格书 §3 + §4 的 requirements/tasks/comment/ref 工具 + §7 页面):
- 后端:requirements/tasks CRUD + 状态机(五态含验收中,自动流转,完成校验无未决任务)、assign/claim/unassign(所有权规则)、验收说明、软删/restore、删除二次确认;comment/activity/ref 多态服务;错误四件套统一
- MCP:requirements.* / tasks.* / comment.* / ref.* / project.* / agent.whoami 工具(~25 个);TokenVerifier 接入 02 的 api_key 服务;cursor 分页;mcp CLI 端到端验证"agent 认领→完成→需求进验收中"
- Web:需求列表(默认列表,可切换)/详情(关联任务/引用/评论/活动/验收)、任务看板(默认看板,dnd-kit 选型在此验)/详情(认领/开始/验收/取消按权限)
- 测试:后端状态机全路径+所有权+并发;前端看板渲染+权限按钮

产出:人类在 Web 管需求任务、agent 经 MCP 干活的完整闭环。

## Answer

闭环全部落地:后端 73 测试(含 MCP 端到端子进程) + 前端 10 组件测试全绿;`python -m app.mcp_server` 独立起服。

**后端(单代码库,service 层供 API/MCP 共享)**
- `errors.py` 错误四件套:AppError(code∈permission_denied/not_found/conflict/invalid_request + unauthorized),FastAPI handler 统一 JSON {code,message};02 票全部 service 迁移,状态码语义不变
- `services/workflow.py` 五态状态机:`start(backlog→in_progress)/ complete(上下文:in_progress→verifying 提交,verifying→done 验收+说明必填)/ cancel(任意未决态)`;需求自动流转只升级(首任务开工→实现中;全任务离开未决→验收中,无任务不流转);验收校验无未决任务(含 backlog,比规格字面严,取 ticket 03"完成校验无未决任务")
- `services/requirements.py` / `tasks.py`:CRUD + 软删/restore;删除二次确认(任务数 mismatch→conflict);认领用条件 UPDATE 原子化,并发竞争败者得 conflict(OperationalError 兜底),线程级并发测试(文件库真实写竞争)
- 所有权规则:已指派任务仅本人/工作区 admin/项目 owner 可改状态/改派/删除;未指派任何编辑权者可操作;**验收(verifying→done)任何编辑权主体可执行**(§3.2)
- `services/polymorphic.py`:comment/activity/ref 多态;target 支持 requirement/task/document/project(user 目标 project_id NOT NULL 挂不住,维持 02 票已知缺口);评论删除 editor 仅自己的/owner+admin 任意;引用双向列表、双方须同项目;活动只追加
- cursor 不透明分页 `pagination.py`:base64url{offset, 条件哈希},跨条件复用游标→invalid_request;HTTP 与 MCP 共用
- API:requirements/tasks 全操作端点 + targets/{type}/{id} 评论/活动/引用(错误体 {code,message})

**MCP(mcp Python SDK 1.29,锁 `>=1.29,<2`)**
- FastMCP + `AuthSettings` + `TokenVerifier` 协议实现(`ApiKeyTokenVerifier`):Bearer key → token_hash 查未吊销 key → agent 主体;`AuthContextMiddleware` contextvar 注入工具层;错误映射为 MCP 错误消息前缀 `code: message`
- 29 工具点号命名空间全注册;cursor 分页、二次确认、所有权全部复用 service
- **端到端验证(§9 事实)**:mcp SDK 1.28/1.29 自带 client 传输在本环境有 bug(对 stock FastMCP server 同样复现,响应不送达),故 E2E 测试用最小 wire 协议客户端(httpx+SSE 解析)打真实 uvicorn 进程:initialize→会话→工具链 **agent 认领→开工→提交→需求自动进验收中→任务验收→需求验收→done**,坏 key 401、跨条件游标 invalid_request 全验证

**Web(Vite+React+TS+Tailwind+shadcn)**
- 项目页壳(需求/任务 tab + 角色 Context);需求页列表默认可切换看板 + 状态过滤 + 删除二次确认对话框;任务页看板默认(拖拽改状态:dnd-kit core,拖到实现中=start/验收中=complete/已取消=cancel,已完成列禁放——验收需说明,走详情页)
- 需求详情(关联任务/引用面板/评论流/活动流/验收对话框/取消)、任务详情(认领/开工/提交/验收/取消/解除指派按权限)
- 前端 10 测试(登录 3 + 成员 2 + 看板 3 + 需求页 2)

**判定记录**
- tasks.complete 上下文双义(提交/验收):工具面无独立 submit/accept(§4.2 表只有 complete),按当前态分流;验收必留说明
- 需求验收的"未决"取三态(backlog/in_progress/verifying),与自动流转的"未进入验收"(backlog/in_progress)区分——需求进验收中后新增 backlog 任务会挡住验收(防绕过)
- 任务删除/恢复走所有权(删除视同改状态);restore 任何编辑权
- 指派目标须为项目成员(非成员任务会死锁,invalid_request 守卫)
- mcp 2.0 重构 auth/FastMCP 结构,锁 1.29 线(pyproject 注释);SDK client 传输 bug 记录于 §9 交接事项
