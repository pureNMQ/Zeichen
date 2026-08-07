# Multica 竞品调研：Zeichen 的能力差距与优先级

调研日期：2026-08-05  
对比对象：[`multica-ai/multica`](https://github.com/multica-ai/multica) 的 `main` 分支、随仓库发布的官方文档和自托管指南。功能核验基线为 [`c98a01b3`](https://github.com/multica-ai/multica/commit/c98a01b3df9124c6a0e86d4384a2140b7f0af1bb)；本文只引用第一方材料。“Zeichen 当前”以本仓库已提交的代码为准，设计规格中尚未落地的项目会明确标为“规划”。

## 结论

Multica 的核心竞争力不是项目看板，而是将 **任务分派 → 可执行运行时 → 运行记录/实时反馈 → 可复用技能 → 自动化与多 Agent 协作** 做成闭环。Zeichen 当前已经具备“人和 Agent 共同使用项目资源”的基础（项目权限、Agent API key、任务/需求、评论、活动、文档，以及标准 MCP），但产品边界明确设为“只记录、不调度”。因此，在“托管编码 Agent”这一直接竞争维度上，最大的缺口是**执行控制面**，而非再增加一种任务视图。

如果 Zeichen 保持“外部 MCP 客户端中的协同/记忆系统”定位，这不是缺陷，而是差异化；如果目标是与 Multica 争夺“让 Agent 成为团队成员”的场景，则需要先接受产品边界的改变，再按下面的 P0→P2 建设。

## Multica 已验证的产品能力

| 能力 | Multica 的具体做法 | 证据 |
| --- | --- | --- |
| 托管执行 | Agent 是长期身份和配置，真正执行由绑定 runtime 上的编码工具完成；任务进入队列后由 daemon 认领。 | [Agents](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/agents.mdx)、[Daemon and runtimes](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/daemon-runtimes.mdx) |
| 本地/云端运行时 | 每台连接电脑运行 daemon，自动发现本机 CLI；通过持久连接接收任务，轮询作兜底。runtime 离线、心跳、重连、并发上限和任务重试均有定义。 | [Daemon and runtimes](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/daemon-runtimes.mdx) |
| 多工具兼容 | 官方工具表列出 Codex、Claude Code、Copilot CLI、OpenCode、Cursor Agent 等 18 个工具，均支持会话续接；其中多数可由 Multica 下发 MCP 配置。 | [AI coding tools comparison](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/providers.mdx) |
| 可观测的执行语义 | 业务 Issue 状态与一次 Task/run 生命周期分离；执行日志可停止或重试，进度回写到 Issue 或聊天窗口。 | [Assign issues to agents](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/assigning-issues.mdx)、[Put agents to work](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/triggering-agents.mdx) |
| 对话即调度 | 指派、评论 `@mention`、回复上下文、直接聊天、自动化都可触发 Agent；连续评论会合并，降低重复运行和排队噪声。 | [@-mention agents in comments](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/mentioning-agents.mdx)、[Put agents to work](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/triggering-agents.mdx) |
| Agent 编排 | Squad 由 leader agent 先接收任务，再通过明确的 `@mention` 分派给成员；leader 的状态、评估、再触发和去重规则是系统级协议。 | [Squads](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/squads.mdx) |
| 技能资产化 | workspace skill 以 `SKILL.md` 加脚本/模板/参考资料的形式保存，可从 URL、归档或 runtime 导入，能绑定多个 Agent 并独立启停。 | [Skills](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/skills.mdx) |
| 自动化 | Autopilot 以 runbook、assignee 和 cron/webhook/manual 触发器组成；支持“创建 Issue”或“仅执行”，有幂等键、事件过滤、交付记录、重放和失败自动暂停。 | [Autopilots](https://github.com/multica-ai/multica/blob/main/apps/docs/content/docs/autopilots.mdx) |
| 工程工具链入口 | 官方文档还覆盖 GitHub PR/CI 状态、GitLab/Gitea/Forgejo 集成及 Slack/Feishu 通道，把外部事件和团队对话纳入任务入口。 | [GitHub integration](https://multica.ai/docs/github-integration)、[VCS integration](https://multica.ai/docs/vcs-integration)、[Channels](https://multica.ai/docs/channels) |
| 产品和运维成熟度 | 官方仓库包含 Web、Desktop、Mobile 客户端、CLI/daemon 安装流程及自托管 Docker 部署；后端说明了健康检查、指标、升级、反向代理与 WebSocket 配置。 | [仓库根目录](https://github.com/multica-ai/multica)、[CLI and daemon](https://github.com/multica-ai/multica/blob/main/CLI_AND_DAEMON.md)、[Self-hosting](https://github.com/multica-ai/multica/blob/main/SELF_HOSTING.md) |

## 与 Zeichen 当前实现的差距

| 优先级 | 缺口（相对 Multica） | Zeichen 的现状证据 | 对用户的影响 | 建议的最小落地单元 |
| --- | --- | --- | --- | --- |
| P0 | **没有执行控制面和 runtime** | [规格 §1.3](../docs/spec.md) 明确“只记录、不调度”；当前 `Task` 只有业务状态、指派人和需求关联，没有 run/attempt、runtime、队列字段（[`backend/app/models/requirement.py`](../backend/app/models/requirement.py)）。 | 指派 Agent 只改变记录；不能在用户无需盯守时启动、停止、重试或恢复实际工作。 | 新增 `runtime`、`agent_profile`、`task_run`/`attempt` 三个模型及状态机；先只接一个 Codex daemon，做到领取、取消、日志和结果回写。 |
| P0 | **没有可靠的执行可观测性** | 当前服务只记录 `backlog/in_progress/verifying/done/cancelled` 业务状态；任务状态变化由操作者显式设置（[`backend/app/services/tasks.py`](../backend/app/services/tasks.py)）。 | 无法回答“是否正在跑、跑在哪台机、消耗多少、失败为何、能否重试”。 | 将业务 Task 和执行 Run 分离；Run 至少记录 enqueue/claim/start/finish/fail/cancel、runtime、会话 ID、结构化错误、开始/结束时间与流式日志。 |
| P0 | **Agent 只是 API 身份，不是可配置执行单元** | Agent 当前为 `is_agent` 用户 + API key（[`backend/app/models/user.py`](../backend/app/models/user.py)）；Agent 管理主要是创建、授权与 key 生命周期。 | 不能选择模型、工具、工作目录、环境变量、MCP、并发或运行权限，也无法复用同一 Agent 配置执行多次。 | 将“身份 Agent”和“执行 Agent profile”分层；profile 绑定 runtime/provider/model/instructions/并发，敏感配置单独加密与审计。 |
| P1 | **没有 Provider 适配层和本地 daemon 体验** | 现有 MCP 是让外部客户端调用 Zeichen 的标准入口（[`backend/app/mcp_server/tools.py`](../backend/app/mcp_server/tools.py)），而非 Zeichen 调用编码 CLI。 | 用户仍要自己管理 Codex/Claude/OpenCode 的启动、上下文和回传，无法获得 Multica 的“一处派工、多工具执行”。 | 定义 provider adapter 接口（先 Codex，后 Claude Code/OpenCode）；daemon 报告能力、版本、健康度和容量，服务端只调度能力匹配的 runtime。 |
| P1 | **没有技能的团队级生命周期** | 规格把 agent 的长期记忆作为方向，但代码中尚无 `memory.*` 工具或 cognee service；`docker-compose.yml` 也标明 API/MCP/Web 容器与 cognee 集成仍是骨架。 | 经验无法以可审查、可版本化、可绑定到多个 Agent 的工作包沉淀。 | 把 `SKILL.md` + 资源作为项目/团队资产，支持版本、来源、审查与按 profile 绑定；先复用仓库中的技能目录，避免发明第二种格式。 |
| P1 | **缺少事件驱动自动化** | 未发现 scheduler、webhook trigger 或 runbook 实现；现有 compose 只启动 Postgres/cognee 骨架。 | 日报、巡检、CI 结果处理等重复工作仍需人工建任务和唤醒 Agent。 | 实现 cron + 签名 webhook + 幂等键；首版仅“触发已有任务模板”，随后再支持 runbook 与无 Issue 执行。 |
| P1 | **评论/讨论不能触发或续接 Agent** | 当前有评论和活动 API，但无 Agent 提及解析、触发预览、会话续接或运行去重（[`backend/app/api/polymorphic.py`](../backend/app/api/polymorphic.py)）。 | 协作上下文仍要人工复制到客户端；反馈链路慢且容易漏。 | 在评论中实现显式 mention → 创建 Run；以 `task_id + agent_profile_id` 去重并合并待处理补充，随后加入会话 resume。 |
| P2 | **缺少 SCM/团队消息的集成入口** | 当前源码中未见 GitHub/GitLab/Gitea/Forgejo 或 Slack/Feishu connector。 | PR、CI 失败和聊天中的指令不能自然地进入任务与执行闭环，使用者需跨系统手工转发。 | 在 Run 模型稳定后，优先做 GitHub Webhook + PR 状态回写；聊天机器人应复用相同的权限、mention 和审计路径。 |
| P2 | **没有 Squad/leader 协作协议** | 当前任务只有单一 `assignee_id`（[`backend/app/models/requirement.py`](../backend/app/models/requirement.py)）。 | 无法把“产品交付”这类不确定归属的工作交给具备路由能力的 Agent 团队。 | 先实现只含 Agent 成员的 Squad 与 leader；把派发、停止条件、父任务状态、审计活动明确建模，不要把多 Agent 并行等同于一个 assignee。 |
| P2 | **工作区/部署形态和客户端覆盖较窄** | Zeichen 规格是单团队、单机 Docker Compose（[规格 §1.1](../docs/spec.md)）；当前是 React SPA + FastAPI。 | 对多团队、跨机器/云端 runtime、桌面常驻连接和移动端查看的覆盖弱于 Multica。 | 先把 Team 从单例约束改为 workspace tenancy，并完成 runtime 级授权；Desktop/Mobile 应放在执行闭环稳定后。 |

## 一个容易误判的点：Zeichen 的潜在优势与安全切入点

Zeichen 规划中的“标准 MCP + Agent 作为独立项目主体 + 项目级权限 + 每 Agent 隔离的长期记忆/可授权互通”并不与 Multica 同质：它更适合成为各种现有 Agent 客户端共用的协同与知识层，而不是取代客户端的运行器。[规格 §1.3、§4、§6](../docs/spec.md) 是清晰的产品路线。

但截至本次检查，这部分记忆、搜索、通知、附件及完整容器部署多数仍停留在规格或 compose 占位，不能作为当前已交付的竞争优势。对外表达应区分“已可用”和“设计目标”；否则会在 Multica 已有的安装、运行、监控体验面前显得不可信。

此外，Multica 的执行能力也带来其公开承认的边界：daemon 以本机用户身份运行，任务默认可接触该用户的文件、网络和已登录凭据；官方建议使用专用 OS 用户、容器或 VM 隔离，且其自定义环境变量保存在服务端数据库中。[Security model](https://multica.ai/docs/security-model) 与 [Agent configuration](https://multica.ai/docs/agents-create) 是可借鉴的透明做法。Zeichen 不应据此宣称“外部 MCP 一定更安全”——外部客户端同样可拥有本地权限——但可把**可验证的最小权限、凭据不落中心库、项目级隔离和审计**做成运行时方案的硬约束，而不是后补项。

## 建议的取舍与路线图

1. **先作产品决策（P0 前置）**：是否改变“只记录、不调度”。不改变时，应把定位收窄为 *MCP-native project context and shared memory*，并优先交付 cognee、搜索、附件和稳定部署；不要承诺托管运行。
2. **若决定直接竞争，先完成单 Provider 的执行闭环**：Codex daemon → runtime 注册/心跳 → Task Run 队列 → 流式日志/停止/重试 → 结果写回任务评论。它比 Squads、移动端或多 Provider 更能验证价值。
3. **再提升可重复性与规模**：Agent profile、团队技能和 webhook/cron 自动化应共享同一 Run 模型；否则每个功能都会各自实现一套调度。
4. **最后做编排与多租户**：Squad 是调度策略层，必须建立在权限、去重、运行状态和审计已可靠的基础上。多 workspace、公开 runtime、桌面和移动端则是规模化交付层。

## 调研边界与来源

- Multica 信息来自其官方 GitHub 仓库及官方文档，访问于 2026-08-05；仓库会持续演进，功能可用性应在采购/集成前以目标 release 再验证。
- 本文没有把 GitHub star 数、营销文案或未公开的云服务能力当作功能证据。
- Zeichen 的比较对象为当前工作区代码；“未发现”不表示未来规格不存在，而是表示尚不能从当前可运行源码中验证。
