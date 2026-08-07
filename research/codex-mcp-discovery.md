# Codex Desktop 未识别 ZeichenMCP：同类案例与结论

调研日期：2026-08-06。范围：已确认 `ZeichenMCP` 配置为 enabled，且对 `http://127.0.0.1:8002/mcp` 的新连接能够完成 MCP 初始化并列出 71 个工具，但当前已打开的 Codex Desktop 任务没有对应工具命名空间；同机 OpenCode 能使用该服务。

## 结论

最符合现象的原因不是 MCP 服务、Streamable HTTP 协议或静态 Bearer 头本身，而是 **Codex Desktop 已加载任务持有了旧的、任务级 MCP 工具目录/连接快照**。`codex mcp list` 和手工 `initialize` / `tools/list` 证明的是当前配置与一个新 MCP 客户端可用；它们并不保证已经创建的 Desktop 任务会重新挂载新增的工具。

这是一个有公开同类报告的生命周期问题，而不是官方已经确认的 ZeichenMCP 专属缺陷。优先创建一个新的 `D:\Zeichen` 任务；若仍未注入工具，则完全退出并重新打开 Codex Desktop 后再创建新任务。对于本案的静态 Bearer 鉴权，通常不需要 `codex mcp login`。

## 一手资料：配置和鉴权能力

- 官方配置参考明确支持项目级 `.codex/config.toml`，但**仅在信任该项目时**加载；用户级配置在 `~/.codex/config.toml`。因此 CLI 在 `D:\Zeichen` 中看见服务器，并不排除 Desktop 任务创建时该项目尚未被信任或尚未重载配置。[Configuration Reference — `config.toml`](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)
- 同一参考将 `mcp_servers.<id>.url` 定义为 Streamable HTTP MCP 端点，并明确列出 `http_headers`（“每次 MCP HTTP 请求附带的静态 HTTP 头”）、`bearer_token_env_var`、`auth` 和 `enabled`。所以项目中以 `url` 加 `Authorization = "Bearer …"` 配置本地服务是受支持的形式；它不是只能依赖 OAuth 的连接类型。[Configuration Reference — MCP fields](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)
- 官方 App Server 文档列出 `config/mcpServer/reload`：从磁盘重新加载 MCP 配置，并“queue a refresh for loaded threads”。这说明产品具备刷新路径；但文档没有承诺每个 Desktop 版本、每一种已加载任务状态都会即时重新注入工具，因此不能据此排除旧任务的缓存/刷新缺陷。[Codex App Server API overview](https://learn.chatgpt.com/docs/app-server)

## 高相似公开案例（OpenAI 官方仓库）

下面是公开 issue / PR，属于用户报告或源码变更记录；除非特别说明，不应将其当作对本机根因的官方确认。

| 资料 | 相似证据 | 对本案的意义 |
| --- | --- | --- |
| [#20605](https://github.com/openai/codex/issues/20605)（仍开放） | 报告中，直接 `tools/list` 与新客户端可用，但已经打开的 Desktop 任务保留早期 MCP 工具快照；后续评论报告新建任务可见工具。 | 与“服务/探针可用，当前任务没有 namespace”最接近，支持先新建任务。 |
| [#30716](https://github.com/openai/codex/issues/30716)（仍开放） | Windows Desktop 中，`codex mcp login`、`codex mcp list` 和全新 `codex exec` 均成功，但正在运行的 App 未挂载工具；新会话也无效，完整重启 App 后恢复。 | 虽为插件 + OAuth，仍证明 Desktop 进程的运行时工具注册可能与 CLI 状态不同；若新任务无效，完整重启是有依据的规避手段。 |
| [#19155](https://github.com/openai/codex/issues/19155)（仍开放） | 服务重启并发送 `notifications/tools/list_changed` 后，同一 Codex session 仍使用旧 schema；新 MCP 客户端立即正确。 | 说明现有会话的工具目录可能陈旧，不应以新客户端的 `tools/list` 推断旧任务已刷新。 |
| [#8957](https://github.com/openai/codex/pull/8957)（已合并，2026-01-12） | 标题为 “hot reload mcp servers”。 | 说明官方已经实现配置热刷新方向，但它不是对所有 Desktop 任务状态的兼容性保证。 |
| [#29608](https://github.com/openai/codex/pull/29608)（已合并，2026-06-23） | 标题为 “Shut down superseded MCP managers on refresh”。 | 说明刷新与替换旧 MCP manager 的生命周期近期仍在迭代。 |

官方变更日志在 Codex CLI 0.146.0（2026-07-29）还写有：配置或鉴权变化时保持 MCP 连接和 Apps 工具最新，并在不重启健康连接的前提下重连关闭服务器。这是改进方向；与仍开放的上述问题并存，故不能保证本机旧任务必定实时恢复。[Codex changelog](https://learn.chatgpt.com/docs/changelog#codex-2026-07-29)

## 建议的排障与恢复顺序

1. 在 `D:\Zeichen` 检查该工作区在 Codex Desktop 中已被信任；项目级 `.codex/config.toml` 的前提条件正是信任项目。
2. 不继续使用当前任务。新建一个 cwd 为 `D:\Zeichen` 的任务，确认 MCP 服务仍在运行后，明确要求调用 `ZeichenMCP` 的一个只读工具（例如 `agent.whoami` 或 `project.list`）。
3. 若新任务仍无 `mcp__ZeichenMCP__*` 工具，**完全退出 Desktop 进程并重新启动**，然后再新建任务。不要只刷新当前对话；#30716 表明在某些 Desktop 状态下新对话并不足够。
4. 重启前后均在 `D:\Zeichen` 中执行 `codex mcp get ZeichenMCP`（或 `codex mcp list`），确认 server 仍为 enabled、URL 未变且项目 `.codex/config.toml` 未被改写。若这里变成 missing/disabled，问题回到配置加载/信任/策略层，而不是旧任务目录。
5. 更新到当前 Codex Desktop 版本后再复测；若“新任务 + 完整重启”仍失败，而全新 CLI 客户端/手工 MCP 会话继续成功，应附上版本号、`codex mcp get ZeichenMCP` 的脱敏输出、Desktop 日志和本复现步骤向 OpenAI 提交 issue。不要提交 Bearer token。

## 边界与待验证项

- 本笔记的本机事实仅采用已知的握手与 `tools/list` 成功结果；未将上述公网 issue 的描述当作本机已经证实的内部原因。
- `http_headers` 支持的是官方文档已确认的功能；若配置中直接写入 token，应保持文件被 Git 忽略。更稳妥的形式是使用 `env_http_headers` 或 `bearer_token_env_var`，前提是 Desktop 进程也能取得对应环境变量。
- 若此项目受到组织 `requirements.toml` 或设备管理策略约束，MCP allowlist 可禁用配置中的服务器；应同时检查其是否存在。该限制也见配置参考的 managed MCP allowlist 说明。[Configuration Reference — managed MCP allowlist](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)
