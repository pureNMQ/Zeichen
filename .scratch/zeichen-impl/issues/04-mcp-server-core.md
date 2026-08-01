# 04 MCP server + 第一批工具

Status: open
Type: task
Blocked by: 02, 03

## Question

搭建 MCP server(规格书 §4)并接入第一批域:
- 官方 mcp Python SDK:Streamable HTTP transport、TokenVerifier(Bearer key,复用 02 的 api_key 服务)
- 工具注册脚手架:点号命名空间自动发现,复用 backend service 层(同一套业务逻辑)
- 第一批域:requirements.* / tasks.* / comment.* / ref.* / project.* / agent.whoami(约 25 工具)
- 错误四件套映射为 MCP 错误;cursor 分页统一
- 验证:用 mcp CLI/客户端本地连接,跑通"agent 认领任务→完成→需求进验收中"的端到端链路
- pytest:工具参数校验 + 权限错误语义

产出:可连的 MCP server + 核心域工具;后续域的工具体现在对应票中追加。
