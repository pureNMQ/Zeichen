# Cognee MCP 与 Codex HTTP 握手问题（2026-08-06）

## 结论

Cognee 并没有一个已发现的「专为 Codex 放行 Origin」补丁。它规避这类问题的首选路径是：**默认使用 stdio**；stdio 没有 HTTP `Origin` / `Host` 请求头，因此不会触发 MCP Python SDK 的 DNS-rebinding 检查。若选择 HTTP，Cognee 使用与 Zeichen 同一类的 MCP Python SDK `TransportSecuritySettings`，并提供通用的主机白名单或关闭保护开关；这不是 Codex 专用方案。

所以，Cognee 不能证明 Codex 的非标准/非本机 Origin 在 HTTP 下天然可用。若 Codex 发送的 Origin 不在 `http://localhost:*` 等默认范围，Cognee 的 loopback HTTP 默认同样可能被拒绝。其源码中未见 `codex` 字符串、Codex URL scheme 或 Codex 专属 allowlist；这是对当前公开 `main` 分支 `cognee-mcp/src/server.py` 的源码观察，而不是对所有历史版本或私有部署的断言。

## Cognee 当前实现（可核验事实）

| 项目 | Cognee 的实现 | 对 Codex 问题的含义 |
|---|---|---|
| 默认传输 | `stdio`（classic pipe）；README 同时列出 SSE 与 Streamable HTTP。 | 默认接入不经过 HTTP 安全校验，是最直接的规避方式。 |
| HTTP 启动 | `python src/server.py --transport http --host 127.0.0.1 --port 8000 --path /mcp`。 | 是 Streamable HTTP，正是 Zeichen 使用的类别，因而要处理相同的 Host/Origin 约束。 |
| SDK 与安全层 | 服务端 `from mcp.server import FastMCP`，并导入 `mcp.server.transport_security.TransportSecuritySettings`。 | 不是自写的 CORS/鉴权替代品，而是 MCP Python SDK 的传输安全设置。 |
| 默认 loopback 行为 | `_configure_transport_security()` 在 host 为 `127.0.0.1` / `localhost` / `::1` 且未添加额外 Host 时，明确“让 SDK 使用 localhost defaults”。源码列出的默认 Host 是 `127.0.0.1:*`、`localhost:*`、`[::1]:*`，Origin 是其 `http://` 形式。 | Codex 若以 `localhost` 的正常本地 HTTP Origin 发起请求，可匹配；若发出其他 Origin，则不保证匹配。 |
| 非 loopback / 额外 Host | `MCP_ALLOWED_HOSTS` 是逗号分隔的 `host:*` 模式；Cognee 将它加入 `allowed_hosts`，并机械派生为 `http://{host}` 加入 `allowed_origins`。 | 能安全支持普通 HTTP 域名/局域网 Host；它并不能配置任意 scheme 的 Origin（例如假设的 `codex://…`）。 |
| 关闭保护 | `MCP_DISABLE_DNS_REBINDING_PROTECTION=true` 会构造 `TransportSecuritySettings(enable_dns_rebinding_protection=False)`。 | 是通用兜底，适合受控 LAN/Docker 情境，不应作为公网服务的默认修复。 |
| CORS | HTTP/SSE app 另加 `CORSMiddleware`，来源是 `MCP_CORS_ALLOW_ORIGINS`（默认 `http://localhost:3000`）。 | CORS 与 MCP transport security 是两层不同机制；单改 CORS 不会替代 Host/Origin 校验。 |
| 鉴权 | MCP README 的 API Mode 用 `--api-url` 和可选 `--api-token`；若后端 API 开启鉴权，token 为必需。该 token 是 MCP 服务到 Cognee API 的凭据，不是 HTTP transport-security 的替代物。 | 与 Zeichen 的 Bearer 验证是不同层次：认证成功也不会自动放行被 Origin 检查拦住的请求。 |

来源：Cognee MCP 0.5.5 的发布说明/README（PyPI）[传输、命令和 API Mode](https://pypi.org/project/cognee-mcp/)，以及 2026-08-06 检索到的公开提交 [`38eece5` 的安全配置源码（L106-L152）](https://github.com/topoteretes/cognee/blob/38eece5bbb0cb9f5706fed908abd16dba0f5505e/cognee-mcp/src/server.py#L106-L152)、[`38eece5` 的启动/传输分支（L1868-L2002）](https://github.com/topoteretes/cognee/blob/38eece5bbb0cb9f5706fed908abd16dba0f5505e/cognee-mcp/src/server.py#L1868-L2002)、[HTTP 客户端配置说明](https://github.com/topoteretes/cognee/blob/38eece5bbb0cb9f5706fed908abd16dba0f5505e/cognee-mcp/README.md#L317-L386) 和 [Docker 默认 stdio](https://github.com/topoteretes/cognee/blob/38eece5bbb0cb9f5706fed908abd16dba0f5505e/cognee-mcp/entrypoint.sh#L45-L57)。SDK 中该设置的定义见 MCP 官方 Python SDK [`transport_security.py`](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/transport_security.py)。

## 与 Zeichen 当前修复的对照

| 方面 | Cognee | Zeichen 当前改动 |
|---|---|---|
| 可靠本地接入选项 | stdio 默认；完全避开 HTTP。 | 当前服务是远程 Streamable HTTP；不能用 stdio 替代时需正确配置 HTTP 安全层。 |
| 本地 URL | 文档 HTTP 示例同时使用 `127.0.0.1`，客户端示例常用 `http://localhost:8000/mcp`。 | 把 Codex 的 URL 改为 `http://localhost:8002/mcp` 是合理的兼容性收敛：与 SDK 的 loopback 默认 Origin/Host 范围相符，也避开了数值回环地址的客户端/代理差异。 |
| HTTP 安全设置 | loopback 采用 SDK 默认；部署时用 `MCP_ALLOWED_HOSTS` 或显式禁用。 | 应保留 DNS-rebinding 保护，并仅追加已实测的 Codex Origin/Host 白名单；这比全局关闭保护更小、更安全。 |
| Codex 特例 | 未发现。 | Zeichen 的显式 Codex 白名单是针对已复现请求头的项目级修复，不是 Cognee 通用做法。 |

## 建议

1. 对本机 Codex，优先保留 `http://localhost:8002/mcp`，不要恢复为 `127.0.0.1`，并以真实 Codex `initialize` 请求中的 `Origin`、`Host` 验证精确白名单。
2. 不要把 Cognee 的 `MCP_DISABLE_DNS_REBINDING_PROTECTION=true` 直接照搬到 Zeichen 生产环境；那是放弃该层保护，不是兼容性配置。
3. 如果未来需要零 HTTP 暴露的本机集成，可借鉴 Cognee 额外提供 stdio server 的产品形态；它是架构选择，不能由现有 HTTP endpoint 的 URL 配置直接获得。

## 未知项与边界

- 未找到 Cognee 官方文档或当前公开源码声明“Codex CLI/Desktop 使用何种 Origin”，因此不能把 Cognee 的成功接入归因于某个 Codex 专属 Origin。
- 未验证 Cognee 的 HTTP server 与当前 Codex CLI 的现场握手；上述“可能被拒绝”来自其已公开的 Origin 默认白名单与 SDK 安全语义，需用实际请求验证。
- 本文引用的是截至本文日期可查询到的 PyPI `cognee-mcp` 0.5.5 与 GitHub `main`；二者可能存在尚未发布的差异，部署时应以锁定依赖版本的源码为准。
