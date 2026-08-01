# 地图:贼船 Zeichen 实现(本地可跑 v1)

## Destination

走完这张地图的产出:**本地可运行的 Zeichen v1 代码库**——规格书(docs/spec.md v1.0)9 章全部落地,本地 Docker Compose 全链路可起、功能可演示(人类 Web 登录、agent 连 MCP、记忆读写)。云服务器部署是地图终点之后的独立收尾(可开新 effort),不进本图。

## Notes

- 域:实现构建(基于已定稿规格书 docs/spec.md);中文交流
- 技能:tdd 常备(后端 pytest 全量 + 前端组件测试);prototype 用于 Web 交互;research 用于实现期事实验证(cognee 端点行为、MCP SDK 用法、IR 编辑器选型)
- 已锁决策(charting 会话):目的地=本地可跑 v1;代码住本仓库(D:\Projects\agent-ops,与 specs/.scratch 同源);前端 Vite+React+TS+Tailwind+Shadcn/ui;后端单代码库分层(SQLAlchemy 2.0+Alembic,api/mcp 共享 service,两进程入口);MCP 用官方 mcp Python SDK;前端 React Router+TanStack Query;测试=后端 pytest 全量+前端组件测试(Vitest+RTL),不做 E2E;构建票按规格书章节切 11 张,每张可运行可验证
- 规格书为唯一依据;spec 的 §9 列有实现时需再验证的事实清单

## Decisions so far

<!-- 每个已解决 ticket 一行:标题链接 + 一句话要点 -->

## Not yet specified

<!-- 在范围内但还不能精确表述的雾;前沿推进后逐步毕业成 ticket -->

- **本地 compose 的确切编排**:cognee 官方镜像在本机的可用性/版本(04 research 提过 cognee/cognee 与 cognee/cognee-mcp,但本地起 service 的细节要试)——等第 1 张工程票推进时验
- **IR 编辑器选型落地**:Milkdown / Bisheng / 其他,哪个与 React+TS+Tailwind 兼容最好——等文档票(第 8 张)推进时验
- **cognee update 端点对会话缓存条目的覆盖范围**:规格书 §9 的待验证事实——等记忆票(第 9 张)推进时验
- **API key 回看的实现细节**:管理员密码验证 + 明文再展示的安全流程——等认证票(第 2 张)细化
- **任务看板的拖拽交互**:看板拖拽改状态的具体实现(库选型 dnd-kit?)——等 Web 任务页票(第 7 张)细化

## Out of scope

<!-- 明确排除在目的地之外的工作;只留 gist + 原因,永远不毕业 -->

- **云服务器部署上线** — 目的地是本地可跑;云部署留待地图完成后的新 effort
- **E2E 测试(Playwright)** — charting 定:后端全量 + 前端组件测试,不做 E2E
- **agent 调度与执行** — 规格书 §1.3 边界,沿用上一张地图的 out of scope
- **多团队** — 规格书单例 Team,沿用
