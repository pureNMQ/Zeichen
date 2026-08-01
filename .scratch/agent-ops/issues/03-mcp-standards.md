# 03 MCP 标准与认证方式

Status: resolved
Type: research
Blocked by:

## Question

调研 MCP(Model Context Protocol)现状并回答:
- 当前协议版本与官方 SDK(FastMCP/Python SDK)的工具面最佳实践:工具命名、结构化参数、资源 vs 工具
- MCP 标准认证规范(Authorization spec)现状:OAuth for MCP 是否可用/推荐;自建 API key(Bearer token)做服务端认证是否合规可行
- 一个 MCP server 暴露多个域(需求/任务/文档/记忆)的常见组织方式:单 server 多工具 vs 多 server
- 服务器端(MCP server 作为远程服务)部署与发现的成熟路径(streamable HTTP?SSE?)

产出:事实清单 + 认证方案对比,写入 research/mcp-standards 分支,链接回本 ticket。

## Answer

已由 research 子代理解决,完整事实清单见 research/mcp-standards.md(commit 7a5c33e)。

要点:
- 协议现状(2026-07 修订,Modern 时代):无握手无会话,每请求 _meta 声明版本;Python SDK v2 中 FastMCP 已更名 MCPServer;工具名 1-128 字符、仅 [A-Za-z0-9_.-]、server 内唯一,官方示例支持点号命名空间(admin.tools.list);inputSchema 缺省 JSON Schema 2020-12
- 认证:Authorization spec 是 OPTIONAL 的;HTTP 传输 SHOULD 遵循 OAuth 2.1 子集;Bearer token 本身就是规范内的令牌形态,SDK TokenVerifier 静态令牌表即文档示范;opencode 原生支持 headers.Authorization + oauth:false
- 多域组织:规范不强制;单实例、工具集小的场景推荐单 server + 点号命名空间(requirements.*/tasks.*/docs.*/memory.*)
- 部署:远程成熟路径是 Streamable HTTP(单 POST 端点、无会话);HTTP+SSE 已废弃;Claude 用 Custom Connectors,opencode 用 type:remote + url + headers
- 认证方案结论:自建 Bearer API key + 严格 Bearer 头/HTTPS/401-403 语义,配合 SDK TokenVerifier,为将来迁移完整 OAuth 预留接口
