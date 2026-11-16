# 设计稿：DSH 原生插件代替 MCP 接入（2026-10-07）

> 状态：**草案，待用户审定后入 Zeichen 立项**。
> 对应计划一。结论先行：后端给 REST `/api` 增加 Bearer API key 认证；新建 Cordis 插件包
> `plugins/dsh-zeichen`（宿主半 60+ 原生工具 + 客户端半 GUI 面板）；MCP 服务器**暂时保留**，
> 第三方客户端（Claude Code / Codex / opencode / ZCode）不受影响。

## 1. 背景与动机

当前 DSH 接入 Zeichen 的链路：

```
DSH(remote profile ~/.dsh/profiles/web)
  └─ @deepseek-ai/dsh-mcp-client ── streamable-http ──► nginx /mcp ──► mcp 容器
       config: url + Authorization: Bearer zc_…(明文写在 cordis.patch.yml)
```

问题清单：

| # | 问题 | 影响 |
|---|---|---|
| 1 | key 明文存储在 `cordis.patch.yml` | 泄露面大，无法走 DSH credentials 加密存储 |
| 2 | MCP 桥接层是黑盒 | 工具无原生 output schema、无 presentCall/presentResult 卡片，DSH GUI 里只能显示泛型 JSON |
| 3 | 桥接层单点 190s 超时 | 长操作体验差，错误码 `code: message` 被压扁成字符串 |
| 4 | REST `/api` 只认会话 cookie | 任何非浏览器程序（插件、idle-runner、脚本）都被迫走 MCP 协议 |
| 5 | 桥接进程常驻 | 多一层部署单元与健康检查面 |

原生插件后的目标链路：

```
DSH host 插件(@zeichen/dsh-plugin)
  ├─ ctx.tools.register × 60+ ── fetch ──► nginx /api (Bearer zc_…，key 走 DSH credentials)
  ├─ ctx.systemPrompt.section(工作流引导)
  ├─ webServer 代理路由 /zeichen-api/*（宿主半注入 key，客户端半不持凭据）
  └─ 客户端半：ctx.slots.register → 侧栏面板图标 + Zeichen 主面板
```

## 2. 决策记录（已与用户对齐 2026-10-07）

- **D1 MCP 去留**：暂时保留。DSH 切原生插件；MCP 继续服务第三方客户端；两通路共用同一
  service 层与权限模型。后续若第三方客户端都迁移到 REST，再评估下线 MCP（单独立项）。
- **D2 范围**：第一期即含 **DSH GUI 集成**（侧栏入口 + Zeichen 面板），不只是工具。
- **D3 流程**：本设计稿审定后入 Zeichen 立项（REQ），任务按里程碑拆分。

## 3. 总体架构

### 3.1 后端：REST `/api` 接受 Bearer API key（前置改造）

`app/api/deps.py::current_user` 扩展为双通道认证：

```
请求 → 有 session cookie？ → 走现有 JWT 校验（浏览器，不变）
     → 无 cookie 但有 Authorization: Bearer zc_…？
         → 按 token_hash 查未吊销 ApiKey（复用 mcp_server/auth.py 的查法）
         → 主体必须存在、未删除、is_agent=true
         → 作为该 agent 用户进入（权限动态继承主人，ADR 0004）
     → 都没有 → 401
```

要点：

- 复用 `security.token_digest` 与 `ApiKey` 表，**不新增任何凭据形态**；
- agent 经 REST 的权限与经 MCP 完全一致（同一 service 层）；
- MCP 的 `AccessToken`/auth_context_var 机制不动，仅把"按 key 找 agent"这段逻辑提为
  共享函数（`services/agents.py` 或新 `services/api_auth.py`），MCP verifier 与 REST deps 共用；
- 速率限制：沿用 nginx；不新增应用层限流（观察后再说）。

### 3.2 插件包 `plugins/dsh-zeichen`（monorepo 内新目录）

```
plugins/dsh-zeichen/
  package.json          # @zeichen/dsh-plugin；peerDependencies 仅声明
                        # @deepseek-ai/cordis、dsh-tools、dsh-agent 等（profile 已具备）
  src/index.ts          # 宿主半入口（Cordis plugin）
  src/tools/*.ts        # 按域拆分：requirements/tasks/docs/comment/ref/project/agent/search/attachment/repositories
  src/client.tsx        # 客户端半入口（React，打包成 window.__ModuleLoader__ 模块）
  src/client/*          # 面板组件
  lib/                  # 构建产物：lib/index.js + lib/client.js
```

**宿主半**注册内容：

1. **工具**（核心）：60+ 工具全部保留现有命名 `requirements.*` / `tasks.*` / `docs.wiki.*` /
   `docs.glossary.*` / `comment.*` / `ref.*` / `project.*` / `agent.*` / `search.*` /
   `attachment.*` / `repositories.*` —— **名字与语义和 MCP 完全一致**，仓库内 8 个 Skills
   零改动即可继续工作。
   - 每个工具：`defineTool` + 原生参数 schema + `output.schema`（JSON Schema）+ `render`
     （喂模型的紧凑文本）+ `presentCall`/`presentResult`（GUI 卡片）+ `timeoutMs`；
   - 执行体：`fetch(baseUrl + path, { headers: { Authorization: Bearer … } })`，REST 路径与
     前端共用（`api/documents.py` 等既有路由）；
   - 错误透传：REST 返回 `{ detail: "code: message" }` → 抛 `HarnessError` 保持
     `code: message` 四件套约定；
   - 生成方式：手写首域（requirements/tasks/docs）作为样板，其余按同一模式补齐；
     不做 OpenAPI 自动生成（描述质量优先，工具数量可控）。
2. **systemPrompt section**：一段 Zeichen 工作流引导（项目上下文、状态确认、留痕纪律的
   精简版，与 Skills/use-zeichen 呼应但不重复全文）。
3. **webServer 代理路由** `/zeichen-api/*`：宿主半注入 API key 转发到 Zeichen REST，
   供客户端半取数；客户端永远见不到 key。
4. **配置**（Config schema）：`baseUrl`（默认 `http://127.0.0.1`）、
   `apiKeyCredential`（DSH credentials 引用，优先）或 `apiKey`（兼容旧方式，标注不推荐）、
   `timeoutMs`、`enabledDomains`（可裁剪不用的域）。
5. **健康检查**：插件启动时探测 `/api/health` 与 `agent.whoami`，失败时工具仍注册但
   systemPrompt 提示连接不可用（避免硬失败拖垮会话）。

**客户端半**（第一期 GUI 范围）：

| 集成点 | Slot | 内容 |
|---|---|---|
| 侧栏面板图标 | `sidebar.panellist`（list，无遮蔽风险） | Zeichen 图标 + 连接状态色点 |
| 主面板 | `main`（keyed，新增 key `zeichen`） | Zeichen 面板 |
| 工具卡片 | `tool.call.toolview`（keyed，按工具名） | 需求/任务/文档操作的原生卡片视图（二期可加） |

Zeichen 主面板（第一期，只读为主）：

- 顶部：项目选择器（`project.list`）；
- 需求/任务速览：按状态分组的列表 + 点开详情（标题、状态、指派、最近活动）；
- 文档速览：wiki 树浏览 + 内容预览（只读，编辑继续去 Zeichen Web 工作台）；
- 数据全部经 `/zeichen-api/*` 代理拉取，复用宿主半的 fetch 与缓存。

### 3.3 构建与部署

- **构建**：`tsup`（esbuild 封装）双入口构建：`lib/index.js`（宿主半，ESM，external 全部
  peer deps）与 `lib/client.js`（客户端半，IIFE 包成 `window.__ModuleLoader__.load({id,
  factory})` 格式，external react 与 `@deepseek-ai/dsh-client-*` 运行时）。客户端 bundle
  格式以 `dsh-client-ui-sidebar` 的产物为对照样板。
- **远程档案**（Ubuntu host，主要消费方）：`~/.dsh/profiles/web/cordis.patch.yml` 把
  `mcp-zeichen` 条目替换为 `zeichen-plugin`（name 指向安装后的包），key 从明文改为
  credentials 引用；`pnpm add` 从仓库路径安装。重启 profile 生效（选无会话时段）。
- **本地档案**（本机 Windows DSH）：经 `plugin_manager` 安装同一包；装好后本会话即可
  dogfood 全部工具（当前会话没有 Zeichen 工具，装好即有）。
- **idle-runner**：`scripts/idle-runner/dispatch.py` 从直连 MCP HTTP 改为 REST `/api` +
  Bearer key（3.1 完成后即可迁，独立小任务，不必等插件）。

### 3.4 兼容性与迁移顺序

```
M1  REST Bearer 认证 + 共享 key 解析函数        （后端，向后兼容，无行为变化）
M2  插件宿主半：requirements/tasks/docs 三域样板 + systemPrompt + credentials + 代理路由
M3  其余域工具补齐（comment/ref/project/agent/search/attachment/repositories）
M4  客户端半：构建链路 + 侧栏入口 + Zeichen 主面板
M5  部署切换：远程档案替换 mcp-zeichen；本地档案安装；idle-runner 迁 REST
M6  观察一周 → 决定是否立"下线 MCP"独立需求
```

每步验收：

- M1：`curl -H "Authorization: Bearer zc_…" http://127.0.0.1/api/projects` 返回项目列表；
  浏览器会话行为不变；后端测试全绿。
- M2/M3：在 DSH 会话中以插件工具完成一次完整需求/任务/文档操作流（对齐 use-zeichen 演练）；
  Skills 文档零改动。
- M4：GUI 面板可浏览项目/需求/任务/文档；断网/坏 key 有明确错误提示。
- M5：远程档案重启后 mcp-zeichen 不再加载；第三方 MCP 客户端不受影响（回归验证）。

## 4. 风险与对策

| 风险 | 对策 |
|---|---|
| 客户端半 bundle 格式与 DSH 加载器不匹配 | M4 先做最小 hello-world 面板验证构建链路，再上业务组件 |
| peer deps 版本随 DSH 升级漂移 | peerDependencies 用宽松区间；升级 DSH 后跑一次回归 |
| 远程档案重启影响在跑会话 | 切换选在无会话时段；cordis.patch.yml 先备份（已有 .bak 惯例） |
| 工具 schema 与 MCP 行为漂移 | 工具描述以 `mcp_server/tools.py` 为准逐一移植；M2/M3 验收含并排对比 |
| REST 暴露面扩大 | key 校验逻辑与 MCP 完全一致；nginx 不新增外部端口；文档记录认证语义 |

## 5. 开放问题（立项时确认）

1. 客户端半是否需要独立 settings 页（配置连接/key），还是完全复用宿主半 Config？（倾向后者）
2. `attachment.upload/download` 的 base64 参数在原生工具里保留还是改二进制流？（倾向保留，
   与 MCP 行为一致，后续再优化）
3. 是否为 Zeichen 工具注册 DSH 斜杠命令（如 `/zeichen req`）？（二期再议）
