# 03 MCP 标准与认证方式

Status: open
Type: research
Blocked by:

## Question

调研 MCP(Model Context Protocol)现状并回答:
- 当前协议版本与官方 SDK(FastMCP/Python SDK)的工具面最佳实践:工具命名、结构化参数、资源 vs 工具
- MCP 标准认证规范(Authorization spec)现状:OAuth for MCP 是否可用/推荐;自建 API key(Bearer token)做服务端认证是否合规可行
- 一个 MCP server 暴露多个域(需求/任务/文档/记忆)的常见组织方式:单 server 多工具 vs 多 server
- 服务器端(MCP server 作为远程服务)部署与发现的成熟路径(streamable HTTP?SSE?)

产出:事实清单 + 认证方案对比,写入 research/mcp-standards 分支,链接回本 ticket。
