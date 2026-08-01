# MCP 标准与认证方式 — 调研事实清单

Ticket: `.scratch/agent-ops/issues/03-mcp-standards.md`
调研对象:agent-ops(单实例自托管,提供需求/任务/文档/记忆多域能力的 MCP 服务)
调研日期:2026-08-01
主要来源:官方文档站 modelcontextprotocol.io(含规范原文 specification/)与官方 Python SDK 文档 py.sdk.modelcontextprotocol.io、opencode 官方文档。所有结论均可回溯到所引 URL。

---

## 1. 当前协议版本与官方 SDK / 工具面最佳实践

### 1.1 协议版本

- 当前规范修订版本为 **2026-07-28**(即"Modern"时代);之前的版本 2025-11-25 及更早(2025-03-26、2024-11-05)为"Legacy"时代,采用 `initialize` 握手建立会话。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning.md
- 2026-07-28 起**没有握手、没有会话**:每个请求在 `_meta` 里携带协议版本/客户端信息/能力,服务器独立接受或拒绝每个请求;唯一的发现调用是 `server/discover`。HTTP 上每个 POST 还必须带 `MCP-Protocol-Version` 头。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning.md
- 对旧客户端,官方 Python SDK v2 可以同一份代码同时服务新旧两个时代(自动探测并回退到 `initialize`)。
  来源:https://py.sdk.modelcontextprotocol.io/whats-new/
- 官方 SDK 共 10 种语言,Python / TypeScript / C# / Go 为 Tier 1。Python SDK 需要 Python 3.10+,`pip install "mcp[cli]"`。
  来源:https://modelcontextprotocol.io/docs/2026-07-28/sdk.md
- **重要命名变化:Python SDK v2 中 `FastMCP` 已改名为 `MCPServer`**(`from mcp.server import MCPServer`;v1 的 `mcp.server.fastmcp.FastMCP` 导入路径已删除)。装饰器 API 不变:`@mcp.tool()` / `@mcp.resource()` / `@mcp.prompt()`。
  来源:https://py.sdk.modelcontextprotocol.io/whats-new/ ;https://py.sdk.modelcontextprotocol.io/

### 1.2 工具命名规范(规范原文)

- 工具名长度 **1–128 字符**;**区分大小写**;允许字符仅为 A-Z、a-z、0-9、`_`、`-`、`.`;不得含空格、逗号等特殊字符;**同一 server 内必须唯一**。
- 规范给出的合法示例:`getUser`、`DATA_EXPORT_v2`、`admin.tools.list`(点号分隔的命名空间前缀写法是官方认可的)。
- 工具名唯一性只在单个 server 内生效;聚合多个 server 工具的客户端/代理**可能遇到命名冲突**(如两个 server 都有 `search`),**SHOULD 用 server 前缀做消歧**;且不能依赖 `serverInfo.name` 做消歧(它不保证唯一)。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md
- 工具的 `inputSchema` 遵循 JSON Schema,**缺省方言为 2020-12**;无参数工具推荐 `{"type":"object","additionalProperties":false}`;可选字段 `title`(UI 显示名)、`description`(模型可读)、`icons`、`outputSchema`、`annotations`。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md ;https://modelcontextprotocol.io/seps/1613-establish-json-schema-2020-12-as-default-dialect-f.md

### 1.3 结构化参数(FastMCP/MCPServer 实践)

- 输入 schema 由**函数类型注解自动生成**(类型注解即契约):有默认值的参数自动变为可选;`Annotated[..., Field(description=..., ge=..., le=...)]` 生成参数描述与数值约束;`Literal[...]` 生成枚举;参数较多时用 Pydantic `BaseModel` 打包成结构化"body"。约束违反会在函数执行前被拒绝,并把可读错误返回给模型自行纠正。
- 返回值同样重要:`content` 是给模型读的文本,`structured_content` 是给客户端程序用的结构化数据(工具声明返回类型后自动生成);配合 `outputSchema` 可让客户端做严格校验与类型推导。
- `@mcp.tool()` 还支持 `title=`、`annotations=`(read_only / destructive / idempotent / open_world 提示)与 `name=`、`description=` 覆盖。
  来源:https://py.sdk.modelcontextprotocol.io/servers/tools/ ;https://py.sdk.modelcontextprotocol.io/servers/structured-output/
- 结构化内容(JSON 值)放在 `structuredContent` 字段;为保证向后兼容,返回结构化内容的工具 SHOULD 同时把 JSON 序列化进一个 TextContent 块。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md
- 2026-07-28 起协议没有会话状态:跨调用状态须用显式 handle(工具返回 ID、后续调用带上),并考虑鉴权、不透明性、生命周期、过期报错。这一条与"文档/任务/记忆"这类有状态域直接相关。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md

### 1.4 资源(Resources)vs 工具(Tools)

- **工具 = 模型驱动(model-controlled)**:模型发现并自动调用,用于执行操作;有"人类在环"的强安全要求(UI 明示、确认提示)。
- **资源 = 应用驱动(application-driven)**:由宿主应用决定如何纳入上下文(树/列表选择、搜索、自动包含),用于提供上下文数据(文件、数据库 schema、业务数据);资源以 URI 唯一标识,支持 `resources/templates/list`(URI 模板)、订阅更新、`annotations`(audience / priority / lastModified)。
- 判断准则:需要**动作/写操作/计算**→ 工具;需要**数据/上下文供读取**→ 资源。工具也可以返回 `resource_link` 指向资源。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md ;https://modelcontextprotocol.io/specification/2026-07-28/server/resources.md

---

## 2. MCP 认证规范现状(Authorization spec)

### 2.1 标准内容

- **授权是 OPTIONAL 的**:规范明确"Authorization is OPTIONAL for MCP implementations";HTTP 类传输 **SHOULD** 遵循该规范;**stdio 传输 SHOULD NOT** 走 OAuth,而应从环境变量取凭证(stdio 的安全边界是启动它的进程)。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index.md
- 该规范 = **OAuth 2.1**(IETF draft)的精简子集,基于:RFC 6750(Bearer)、RFC 9728(Protected Resource Metadata)、RFC 8414(AS 元数据发现)、OIDC Discovery、RFC 8707(Resource Indicators)、RFC 9207(iss)、RFC 7591(动态客户端注册,已标记 deprecated,被 Client ID Metadata Documents 取代)。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index.md
- 关键 MUST:
  - MCP server **MUST** 实现 RFC 9728 Protected Resource Metadata(暴露于 `/.well-known/oauth-protected-resource`,并在 401 的 `WWW-Authenticate` 头里用 `resource_metadata` 参数指给客户端);
  - MCP 授权服务器 **MUST** 至少提供 RFC 8414 或 OIDC Discovery 之一;客户端 **MUST** 两种都支持;
  - 客户端 **MUST** 用 `Authorization: Bearer <access-token>` 头发送令牌,**MUST NOT** 把令牌放 URL 查询串;每个请求都必须带认证头。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index.md
- 错误语义:401 = 需要认证/令牌无效;403 = scope 不足(`error="insufficient_scope"` + 所需 scope 列表,触发 step-up 授权);支持按 scope 做最小权限与增量授权。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index.md
- 教程措辞:授权虽 optional,但在"访问用户私有数据、需要审计、企业级访问控制、按用户限流/计量"时**强烈推荐**。OAuth 流程只适用于 HTTP 远程托管场景。
  来源:https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/authorization.md

### 2.2 自建 API key(Bearer)是否合规可行

- 规范层面:"Bearer token"就是标准形态——客户端发 `Authorization: Bearer <token>`,服务端(资源服务器角色)验证令牌。MCP 规范不强制要求走 OAuth 发现/授权服务器,**只要 HTTP 传输遵循该规范即可**,而"令牌如何签发"本就不属于资源服务器职责。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/index.md
- **官方 Python SDK 直接支持静态令牌**:`TokenVerifier` 协议(`verify_token(token) -> AccessToken | None`)是全部集成面,官方文档的示例就是一张静态令牌表(`KNOWN_TOKENS = {"alice-token": ...}`)——即预共享 API key 就是文档示范的写法;配合 `AuthSettings(issuer_url, resource_server_url, required_scopes)` 自动发布 RFC 9728 元数据与 401 挑战。若自己签发 JWT,同样走这个接口做 JWT 验签或 introspection。
  来源:https://py.sdk.modelcontextprotocol.io/run/authorization/
- 生态事实:
  - Claude/Custom Connectors 连接远程 MCP server 时,"认证方式因服务器实现而异,通常涉及 OAuth、API key 或用户名/密码"。
    来源:https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-remote-servers.md
  - opencode 远程 server 配置原生支持 `headers: {"Authorization": "Bearer MY_API_KEY"}`,并可 `"oauth": false` 关闭 OAuth 自动流程(专门用于 API-key 型服务器)。
    来源:https://opencode.ai/docs/mcp-servers/
- 结论:自建 Bearer API key 作为**服务端认证**完全合规且可行——它与规范传输层要求一致(Authorization 头、Bearer 格式、401/403 语义),只是跳过了"发现授权服务器→浏览器授权→换令牌"的完整 OAuth 客户端流程;代价是客户端不会自动走 OAuth 发现,需在客户端配置里显式填 header(这正是 opencode 支持的形态)。
- 注意点:令牌不得放查询串(规范 MUST);生产环境强制 HTTPS(教程要求);stdio 传输下认证不生效(边界是启动进程)。

---

## 3. 多域组织方式:单 server 多工具 vs 多 server

- 规范对"一个 server 暴露多少工具"没有限制,也没有"一个域一个 server"的规定;工具集合可以随请求(按授权 scope)变化,且 SHOULD 保持确定性顺序(利于客户端缓存与 LLM prompt cache)。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md
- 官方认可的名称消歧模式就是命名空间前缀:工具名允许点号(`admin.tools.list`);聚合多个 server 的客户端用 **server 前缀**消歧(如 opencode 实际做法:工具以 server 名作前缀注册,`"mymcpservername_*"` 可整体开关)。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md ;https://opencode.ai/docs/mcp-servers/
- 生态最佳实践(面向**宿主客户端**的官方指南)表明:连几十上百个 server、上千工具时,宿主应做**渐进式发现**(progressive discovery:给模型一个轻量 `search_tools` 元工具,按需加载完整定义)与**动态服务器管理**(server 注册表,按任务按需连接/断开);并按 server 分组呈现工具。对工具定义占上下文比例很小的小规模场景,全量加载即可。
  来源:https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices.md
- 多 server 的实际差异(生态实践,非规范强制):每个 server 独立鉴权(可对"需求/任务"等敏感域单独控制)、独立 `tools/list`(上下文加载粒度)、独立部署/重启/版本、可在客户端按名开关(`tools: {"domain_*": false}`);单 server 多工具的代价是:工具列表一起加载、权限与限流粒度是整 server 级(除非按 scope/请求做细粒度控制)、一个域出问题影响全部。官方客户端的建议是按 server 分组、按需加载,说明**多 server 是生态中宿主能力的主要扩展路径**;但对"单实例自托管、域数量固定且工具集小"的场景,一个 server + 点号命名空间前缀(`requirements.*` / `tasks.*` / `docs.*` / `memory.*`)完全符合规范且运维最简单。
  来源:https://opencode.ai/docs/mcp-servers/ ;https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices.md

---

## 4. 服务端部署与发现的成熟路径(transport)

- 官方传输共三种:stdio(本地)、**Streamable HTTP(远程)**、以及已废弃的 HTTP+SSE(2024-11-05,自 2025-03-26 起 deprecated,新实现 **SHOULD NOT** 采用)。**远程部署的成熟路径就是 Streamable HTTP**。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http.md
- Streamable HTTP 形态(2026-07-28 修订后):服务器暴露**单一 POST 端点**(MCP endpoint,如 `https://example.com/mcp`);每个 JSON-RPC 请求 = 一次独立 HTTP POST;响应要么是单个 JSON 对象,要么是**限定于该请求的 SSE 流**(进度通知 + 最终响应);**没有 GET 流端点、没有协议级会话**(Mcp-Session-Id 已移除)→ 现代流量天然无状态,可放在普通轮询负载均衡后面。服务器对客户端的长生命周期通知改为 `subscriptions/listen` 一条流。服务端安全要求:校验 Origin 头(防 DNS rebinding)、本地部署只绑 127.0.0.1、应实现认证。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http.md ;https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning.md
- 部署细节:服务器应当响应 `X-Accel-Buffering: no`(反代不缓冲 SSE)、长流周期发 SSE 注释行保活;现代请求必须带 `MCP-Protocol-Version` / `Mcp-Method` / `Mcp-Name` 头,网关可纯按头路由与限流。
  来源:https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http.md
- Python SDK 侧:`mcp.run(transport="streamable-http")` 即起在 `http://127.0.0.1:8000/mcp`;也可作为 ASGI 应用挂载进现有 FastAPI/Starlette 应用;v2 的 `run()` 按传输类型给出类型化选项(host/port/endpoint 等)。
  来源:https://py.sdk.modelcontextprotocol.io/run/authorization/ ;https://py.sdk.modelcontextprotocol.io/run/asgi/ ;https://py.sdk.modelcontextprotocol.io/whats-new/
- 客户端接入远程服务器的方式:
  - **Claude(Custom Connectors)**:设置里加连接器,粘贴远程 URL(`https://.../mcp`),按提示完成认证(OAuth / API key / 用户名密码),之后可配置每个工具权限。
    来源:https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-remote-servers.md
  - **opencode**:`"mcp": { "<name>": {"type": "remote", "url": "https://...", "headers": {"Authorization": "Bearer <key>"}} }`;或省略 headers 走自动 OAuth(检测 401 → 动态客户端注册 RFC 7591 → 浏览器授权 → 本地安全存储令牌,`~/.local/share/opencode/mcp-auth.json`);`"oauth": false` 关闭自动流程。工具以 server 名作前缀注册进模型工具列表。
    来源:https://opencode.ai/docs/mcp-servers/
- 自托管单实例结论:FastAPI 挂载或独立 `mcp.run(transport="streamable-http")` + 反向代理(HTTPS 终止、SSE 不缓冲)即为成熟路径;发现机制上,远程 server 无需注册中心——客户端配置里给 URL + 认证信息即可(OAuth 型则靠 `/.well-known/oauth-protected-resource` 自动发现)。

---

## 5. 认证方案对比(面向单实例自托管)

| 维度 | MCP 标准 OAuth 2.1 流程(授权码 + PKCE) | 自建 Bearer API key(静态令牌) |
|---|---|---|
| 规范符合度 | 完全符合 Authorization spec(规范推荐方向) | **传输层合规**:Bearer 头、401/403 语义、RFC 9728 元数据均可照做;跳过客户端发现/授权环节,属"实现自定义的令牌签发" |
| 实现成本(服务端) | 需另部署/接入授权服务器(Keycloak 等)或写完整授权服务器,做 DCR/元数据/consent | 极低:一张静态令牌表即可,Python SDK `TokenVerifier` 官方示例即此形态 |
| 客户端配置成本 | 客户端自动发现(401→PRM→AS→授权),用户浏览器点一下即可;opencode/VS Code 等开箱即用 | 每个客户端手动配 header(`Authorization: Bearer <key>`);opencode 支持,Claude Connector 亦可(官方文档明示 API key 是常见方式) |
| 单租户自托管 | 过重:授权服务器、回调地址、浏览器流程为多用户/多客户端场景设计 | **恰好匹配**:单实例、单租户、客户端数量少,一个 key 即可覆盖 |
| 细粒度权限 | scope 机制成熟(可 step-up 增量授权) | 无原生 scope;可在工具内用 `get_access_token()` 读令牌身份做每工具规则,或维护多个 key |
| 令牌生命周期 | 短时 access token + refresh token,可吊销/轮换 | key 即长期凭证;需人工吊销/轮换;泄露面更大(注意:规范要求令牌不走查询串、强制 HTTPS) |
| 审计 | 有签发方记录 | 依赖服务端自行记录 key 使用日志 |

**推荐(单实例、单租户自托管工具)**:采用**自建 Bearer API key 方案**,但严格按规范的传输层要求落地:

1. 走 `Authorization: Bearer <key>` 头(绝不进查询串),强制 HTTPS;
2. 服务端用 Python SDK 的 `TokenVerifier` 接口(静态表或自己的 JWT 验签),并配置 `AuthSettings` 自动获得 `/.well-known/oauth-protected-resource` 元数据与规范的 401 挑战——这样即便将来某个客户端想走 OAuth 发现也能得到正确的元数据;
3. 为"需求/任务/文档/记忆"等多域维护**不同 key 或 scope 标记**,在工具内按 `get_access_token()` 做每工具授权,为迁移到标准 OAuth 预留接口;
4. 客户端侧:opencode 用 `headers.Authorization`(必要时 `"oauth": false`);若未来要开放给多租户/多方客户端,再升级为完整 OAuth 2.1 授权服务器(Keycloak 等),服务端代码无需推翻(TokenVerifier 换成 introspection 即可)。
