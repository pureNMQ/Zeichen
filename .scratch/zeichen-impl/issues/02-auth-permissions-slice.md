# 02 认证与权限闭环(后端 + Web)

Status: resolved
Type: task
Blocked by: 01

## Question

实现认证/权限(规格书 §5)完整闭环——第一张"人类能登录、能管理"的垂直切片:
- 后端:账号+密码登录、会话(JWT/Cookie)、首用户引导(创建 admin)、成员直接添加(账号+角色,首登设密码)、API key 生命周期(仅 agent 签发/多 key 独立吊销/哈希存储/回看明文-管理员密码验证)、两级角色权限服务(admin 自动全项目 owner,判权只看角色)
- Web:登录页、首用户引导注册页、用户菜单(改密码/退出)、项目列表页(admin 见全部/member 见已加入)、成员管理页(添加/改角色/移除)、Agent 管理页(创建/授权/key 管理含回看/吊销)
- 测试:后端 pytest(认证流+权限矩阵全覆盖)、前端组件测试(登录流/成员列表渲染)

产出:可注册、登录、建项目、管成员/agent 的完整闭环(项目内页面留空占位)。

## Answer

闭环全部落地,后端 38 测试 + 前端 5 组件测试全绿,uvicorn 冒烟通过。

**后端(单代码库分层,api 薄路由 + service 层,供 MCP 复用)**
- `app/security.py`:argon2(pwdlib)密码哈希;HS256 JWT 会话 cookie(HttpOnly/Lax,typ=session 与 set_password 短令牌 1h);API key 明文仅签发瞬间返回,落库 sha256 `token_hash`(唯一索引,供鉴权查重)+ AES-GCM `token_encrypted`(服务端密钥派生,回看解密)
- 权限服务 `services/permissions.py`:两级角色判权;admin 自动全项目 owner;`get_accessible_project` 非成员 404(不泄露存在性)/成员权限不足 403
- auth API:bootstrap(空库 409 守卫)/login(agent 403、无密码成员返回 needs_password)/set-password/change-password/logout/me
- members API(仅 admin):添加(无密码行,首登设密码)/改角色/移除(软删 user + 清 workspace/project 成员行);最后一名 admin 不可降级/移除
- agents API(仅 admin):创建/改授权(整组替换)/删除(软删 + 全吊销 + 清 project_member/memory_grant);key 签发/列表(不回明文)/回看(admin 输自己密码)/独立吊销(幂等)
- projects API:admin 建项目(自动 owner 行)/列表(admin 全量、member 已加入)/详情/成员增删(owner/admin;最后 owner 守卫计入 admin 虚拟 owner)
- 依赖新增:pwdlib[argon2]/pyjwt/cryptography;迁移 `fae8db738539`(api_key.token_encrypted),PG+SQLite 双路径验证

**Web(Vite+React+TS+Tailwind+shadcn,React Router 7 + TanStack Query 5)**
- 登录页、首用户引导页(自动跳转)、首登设密码页、AppShell(侧栏按 admin 显隐 + 用户菜单:改密码对话框/退出)
- 项目列表页(admin 见全部 + 新建;member 见已加入,项目内占位)、成员管理页(添加/角色下拉/移除)、Agent 管理页(创建/Key 管理对话框:签发一次展示、管理员密码回看、吊销)
- vite dev proxy `/api → :8000`(同源 cookie,免 CORS);Vitest 4 + RTL + jsdom 组件测试 2 文件 5 用例

**判定记录**
- 密码策略:≥8 位(规格未定,实现补齐)
- 移除成员 = 软删 user(§2.1 业务实体一律软删),用户名随墓碑占用不可复用
- agent 不建 workspace_member 行(不在"成员管理"页,只走项目授权)
- 工作区级事件(成员/key 变更)不记 activity:activity.project_id NOT NULL 无法表达,列为 03 票后已知缺口
- 人类成员加入项目前必须是工作区成员(agent 例外,400 守卫)

