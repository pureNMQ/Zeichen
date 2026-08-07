# 地图:贼船 Zeichen 实现(本地可跑 v1)

## Destination

走完这张地图的产出:**本地可运行的 Zeichen v1 代码库**——规格书(docs/spec.md v1.0)9 章全部落地,本地 Docker Compose 全链路可起、功能可演示(人类 Web 登录、agent 连 MCP、记忆读写)。云服务器部署是地图终点之后的独立收尾(可开新 effort),不进本图。

## Notes

- 域:实现构建(基于已定稿规格书 docs/spec.md);中文交流
- 技能:tdd 常备(后端 pytest 全量 + 前端组件测试);prototype 用于 Web 交互;research 用于实现期事实验证(cognee 端点行为、MCP SDK 用法、IR 编辑器选型)
- 已锁决策(charting 会话):目的地=本地可跑 v1;代码住本仓库(D:\Projects\agent-ops);前端 Vite+React+TS+Tailwind+Shadcn/ui;后端单代码库分层(SQLAlchemy 2.0+Alembic,api/mcp 共享 service,两进程入口);MCP 用官方 mcp Python SDK;前端 React Router+TanStack Query;测试=后端 pytest 全量+前端组件测试(Vitest+RTL),不做 E2E
- **构建策略:垂直切片**——每张票 = 一个人类可用的完整闭环(后端+前端+测试),不积攒大爆炸
- **优先级决定(测试反馈)**:优化票 **08-14 全部先于 04-07** 新增功能开发,顺序 08→09→10→11→12→13→14;04-07 一律排在 14 之后
- **草稿流程**:用户测试发现的优化点先收集在 `issues/optimization-backlog.md`(单文件合并,**不参与认领/分发**);全部整理完成、用户逐项确认(含遗留决策)后,拆分回 `issues/NN-<slug>.md` 独立可执行票(去掉草稿态)再分发 → ✅ 2026-08-02 已逐项确认并拆分为 08-14(严格垂直切片,09 含状态机+MCP+看板+文档修订)
- 规格书为唯一依据;spec 的 §9 列有实现时需再验证的事实清单

## Decisions so far

<!-- 每个已解决 ticket 一行:标题链接 + 一句话要点 -->

- [01 工程骨架+数据模型+迁移](issues/01-scaffold-data-model.md) — 15 表全建、迁移双路径(PG/SQLite)干净;五件套按语义落(工作区级实体无 project_id);cognee 1.4.1 镜像拉取成功,默认 auth=required
- [02 认证权限闭环](issues/02-auth-permissions-slice.md) — JWT 会话 cookie + 首用户引导 + 成员首登设密码;API key 哈希+AES-GCM 存储、admin 密码验证回看;两级角色判权 admin 自动 owner;Web 登录/项目/成员/Agent 页全闭环(38 后端 + 5 前端测试)
- [03 需求/任务闭环](issues/03-requirements-tasks-slice.md) — 五态状态机(提交/验收双义 complete)+ 自动流转 + 所有权规则 + 认领原子化;错误四件套统一(API/MCP 同源);29 个 MCP 工具 + TokenVerifier(Bearer key)+ cursor 分页;Web 需求列表/详情 + 任务看板(dnd-kit 拖拽)/详情;E2E 打通"agent 认领→完成→需求进验收中"(73 后端 + 10 前端测试)
- [11 表单 autocomplete 规范](issues/11-autocomplete-standard.md) — 根 AGENTS.md 固化显式 autoComplete 规则；Input/Textarea 编译期强制声明，业务字段与密码语义已全站补齐并经前端回归验证。
- [12 成员角色锁定与 Owner 转让](issues/12-member-role-lock.md) — 首用户与本人角色/移除锁定；项目 Owner 仅可经当前密码确认转让，原 Owner 自动降为 editor；共享下拉框默认向下展开。
- [08 侧边栏导航与当前项目](issues/08-sidebar-navigation.md) — 团队/工作区两区导航、全局当前项目切换器、项目详情成员授权与改名闭环。
- [09 自由状态交互](issues/09-state-interactions.md) — 需求四态、任务五态均可自由转换；API/MCP 与看板交互、文档同步完成。
- [10 状态下拉与需求任务关联](issues/10-status-dropdown.md) — 卡片和详情状态下拉、需求与任务双向关联入口及回归测试完成。
- [13 管理页卡片布局](issues/13-management-card-layout.md) — 成员和 Agent 管理页转为响应式卡片，管理能力集中且沿用权限锁定。
- [14 Agent Key 管理交互](issues/14-agent-key-management.md) — Key 默认展开、图标操作、即时隐藏吊销项及明文复制闭环。
- [16 普通成员只读查看成员](issues/16-member-read-access.md) — 已认证工作区成员可查看团队成员；有项目访问权的成员可查看项目成员与角色，所有管理接口及控件仍按 admin/Owner 严格限制。
- [17 跨语言代码签名文本输入](issues/17-code-signature-text-input.md) — 后续增强：为 MCP 代码符号写入提供受限、可验证的 Python/C# 等声明文本解析；当前版本仅接受结构化 definition。
- [04 文档闭环](issues/04-docs-slice.md) — Wiki/字典/API 共用版本化文档域；Milkdown 即时渲染编辑、MCP docs.* 工具、API schema 校验与引用预警已完成。

## Not yet specified

<!-- 在范围内但还不能精确表述的雾;前沿推进后逐步毕业成 ticket -->

- **本地 compose 的确切编排**:cognee 官方镜像在本机的可用性/版本——等第 1 张工程票推进时验
  → ✅ 已验(01):`cognee/cognee:latest` 1.4.1 可拉取,compose 骨架就位;API 端口/健康端点待 05 票确认
- **IR 编辑器选型落地**:Milkdown / Bisheng / 其他,哪个与 React+TS+Tailwind 兼容最好——等文档票推进时验
- **cognee update 端点对会话缓存条目的覆盖范围**:规格书 §9 的待验证事实——等记忆票推进时验
- **mcp SDK 版本与客户端传输**:→ ✅ 已验(03):SDK 2.0 重构 auth/FastMCP,锁 1.29 线;1.28/1.29 自带 client 传输在本环境有 bug(响应不送达),E2E 用最小 wire 协议客户端

## Out of scope

<!-- 明确排除在目的地之外的工作;只留 gist + 原因,永远不毕业 -->

- **云服务器部署上线** — 目的地是本地可跑;云部署留待地图完成后的新 effort
- **E2E 测试(Playwright)** — charting 定:后端全量 + 前端组件测试,不做 E2E
- **agent 调度与执行** — 规格书 §1.3 边界,沿用上一张地图的 out of scope
- **多团队** — 规格书单例 Team,沿用
