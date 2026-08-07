# 使用 MCP 发现／加载远程 Skill 的项目调研

调研日期：2026-08-07  
范围：核验「Agent 或 MCP 兼容宿主能否经 MCP 发现、读取远程 Agent Skill」；优先采用 MCP 官方规范、项目官方 README 与固定提交的源码。本文的“加载”指拿到 `SKILL.md`（及必要的辅助文件）并将其作为当前任务的指令／上下文使用，不等同于下载安装到本机或将代码直接执行。

## 结论

**有，且已有一个 MCP Skills Extension 草案及主干 Agent 实现。**`evalstate/fast-agent` 是最强的通用端到端证据：它连接远程 MCP server 后，按草案发现能力，执行 `skills/list → skills/get → resources/read`，校验 SHA-256 后安装本地副本。OpenAI Codex 主干还有一条不同的、产品限定的路径：仅从 `codex_apps` MCP server 的 resources 中筛出 `mcp/skill`，再按需读取。除此之外，`afriemann/skills-mcp`、`K-Dense-AI/claude-skills-mcp` 和 `AlexFischman/mcp-skill-creator-agency` 分别展示了自定义 Skill gateway、服务端预索引和 Agent 消费后端的实现。

但应避免称其为“已标准化的 MCP Skill 加载”：已采纳的 MCP 2025-11-25 核心规范仅有 **tools、resources、prompts**，没有 `skills/list`、`skills/get` 或 Skill 安装／激活生命周期。官方仓库中的 **SEP-2640** 已提出 `io.modelcontextprotocol/skills` 扩展和上述方法，但其状态为 Draft，尚非正式标准。因此自定义 gateway、Codex 专用路径与 SEP-2640 实现三者不能混为一谈；宿主是否把取回的内容注册、安装或激活为原生 Skill，仍由 Agent 框架决定。

## 项目筛选标准

纳入项目须同时满足：

1. 有可核验的一手源码或官方文档；
2. Skill 来自 GitHub、HTTP 或独立远程 MCP 服务，而非只读取同一进程的本地目录；
3. MCP 在链路中承担了 Agent/宿主与 Skill 服务之间的发现、检索或读取接口；
4. 明确标注其实际边界：仅把 Skill 内容作为工具结果／资源返回，还是 Agent 真的通过 MCP 客户端消费它。

排除项包括：仅提供普通业务 MCP tools、只把“skill”写在项目描述中、或仅把 MCP server 配置同本地 Skill 一起分发但不通过 MCP 返回 Skill 内容的项目。

## MCP 规范边界

| 标准能力 | 规范所定义的作用 | 与远程 Skill 的关系 |
| --- | --- | --- |
| Tools | 客户端以 `tools/list` 发现、以 `tools/call` 调用；结果可返回文本或结构化内容。 | 各项目最常用的 Skill 目录／正文读取接口。 |
| Resources | 客户端可 `resources/list`、`resources/templates/list`、`resources/read` 发现和读取资源。 | 可将 `SKILL.md` 表示为自定义 URI 的资源。 |
| Prompts | 客户端以 `prompts/list`／`prompts/get` 获取参数化 prompt。 | 与完整目录型 Skill 不同；不替代 Skill 的辅助文件与宿主激活逻辑。 |

规范来源：MCP 官方仓库固定版本的 [Tools](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/9d4a9115126f1356f4b189af3266c1839a4e9bbb/docs/specification/2025-11-25/server/tools.mdx)、[Resources](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/9d4a9115126f1356f4b189af3266c1839a4e9bbb/docs/specification/2025-11-25/server/resources.mdx) 与 [Prompts](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/9d4a9115126f1356f4b189af3266c1839a4e9bbb/docs/specification/2025-11-25/server/prompts.mdx)。三份规范均列出各自的协议消息与 capability；未定义 Skill capability。这是“无**已采纳核心规范** Skill 原语”的依据，而非声称协议禁止自定义或草案扩展。

## SEP-2640 草案与最强落地证据

MCP 官方仓库的 [SEP-2640 Skills Extension（固定草案）](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/d7490ecd1a250f7bc8c3ebb0d65450dfec274bad/seps/2640-skills-extension.md) 状态为 **Draft**。它定义 `io.modelcontextprotocol/skills` capability：用 `skills/list` 枚举、`skills/get` 获取某个 Skill 的 metadata 与完整文件 manifest，再用既有的 `resources/read` 读取每个文件；Skill 格式本身委托给 Agent Skills specification。草案要求 host 对 manifest 中每个文件的 SHA-256 做验证，并要求每个 Skill 的激活获得独立、明确的用户同意。因此它是“远程 Skill 经 MCP 传输”的正式提案，**不是**当前所有 MCP 客户端均可依赖的标准。

| 项目 | 实现状态与证据 | 判定 |
| --- | --- | --- |
| [`evalstate/fast-agent`](https://github.com/evalstate/fast-agent) | 官方文档明确标注兼容 SEP-2640 固定 Draft、并说明从已连接 server 发现 capability 后执行分页 `skills/list`、`skills/get`、`resources/read`、SHA-256 校验和本地写入；给出远程 Hugging Face MCP server 连接例子。源码中的 registry client 也按 capability 扫描和分页处理。 | **是，最强的通用 Agent host 实现。**它是草案实现，不声称协议已 ratified；安装后使用的是显式本地副本，不是透明远程上下文。 |
| [`openai/codex`](https://github.com/openai/codex) | `OrchestratorSkillProvider` 在主干中检查固定 `codex_apps` server，对其调用 `resources/list`，仅接收 MIME type `mcp/skill` 的资源，并以 `resources/read` 按需读取。 | **是，OpenAI 主干的 Agent 专用实现。**但它是 `codex_apps` + `mcp/skill` metadata 的产品协议，既非通用 MCP 核心能力，也非 SEP-2640 实现。 |

### `fast-agent`：按 SEP-2640 下载、校验、安装

- [Skills over MCP 文档（固定提交）](https://github.com/evalstate/fast-agent/blob/79b903c601146287b06d4fd61ce30ab8c4c177df/docs/docs/mcp/skills-over-mcp.md) 第 14–28 行明确其只兼容 SEP-2640 Draft，具体流程为 capability discovery、`skills/list`、`skills/get`、读取 manifest 声明的 resources、逐文件 SHA-256 校验后写入本地。
- 同文档第 64–80 行给出真实远程 MCP endpoint `https://huggingface.co/mcp` 的连接示例；第 111–114 行特别说明它不把 MCP resource 直接暴露给模型，而是安装为显式本地副本。
- [MCP registry 源码（固定提交）](https://github.com/evalstate/fast-agent/blob/79b903c601146287b06d4fd61ce30ab8c4c177df/src/fast_agent/skills/mcp_registry.py) 中的 `server_supports_mcp_skills`、`scan_mcp_skill_registry` 和 `get_mcp_registry_skill` 对应 capability 检查、`skills/list` 与 `skills/get` 的客户端实现。

### OpenAI Codex：限定在 `codex_apps` 的资源型 Skill catalog

- [Orchestrator provider 源码（固定提交）](https://github.com/openai/codex/blob/b94343ab9f3f3e77f945d88eb10743bbd15eb8d3/codex-rs/ext/skills/src/provider/orchestrator.rs#L25-L206) 定义 `mcp/skill` MIME type；先检查并对 `CODEX_APPS_MCP_SERVER_NAME` 调用 `list_resources`，再以 `read_resource` 读取选中的 Skill resource。
- 该代码明确把来源 authority 固定为 `codex_apps`，所以不能推论为 Codex 对任意第三方远程 MCP server 自动加载 Skills 的公开互操作承诺。它证明的是一个 mainline Agent 对 MCP resources 承载 Skill 的生产级内部／产品集成。

Anthropic 的官方 Skills 仓库也将 Skill 定义为包含 `SKILL.md`、指令、脚本和资源的目录，并说明由 Claude 动态加载；这解释了为何仅返回一段 prompt 通常不足以完整表达 Skill：[README（固定提交）](https://github.com/anthropics/skills/blob/b29e7cf65e5cb78a5ac33d582270551bc74a14eb/README.md)。

## 已核验项目

| 项目 | MCP 在链路中的角色 | 远程来源与发现／读取证据 | 判定 |
| --- | --- | --- | --- |
| [`afriemann/skills-mcp`](https://github.com/afriemann/skills-mcp) | 专用 MCP Skill gateway（stdio server） | 含 ref）和直连 配置支持 GitHub 多 Skill 仓库（HTTP `SKILL.md`；向客户端提供 `list_skills`、`get_skill` 及 `skill://` resource template。GitHub adapter 会递归枚举 `SKILL.md`，再按选择读取正文和辅助文件；HTTP adapter 读取配置 URL。 | **是，最直接匹配。**Agent 通过 MCP 按需发现／读取远程 Skill；项目明确不做本地安装或同步。 |
| [`K-Dense-AI/claude-skills-mcp`](https://github.com/K-Dense-AI/claude-skills-mcp) | MCP Skill 检索与渐进读取服务 | 后端将 `find_helpful_skills`、`read_skill_document`、`list_skills` 注册为 MCP tools；加载器支持 GitHub URL，将仓库 tarball 缓存后枚举 `SKILL.md` 及文档。 | **是，但为“服务端预加载 + MCP 检索”，不是客户端直接访问任意 URL。**README 已声明项目不再维护，适合作为实现参考而非新依赖。 |
| [`AlexFischman/mcp-skill-creator-agency`](https://github.com/AlexFischman/mcp-skill-creator-agency) | 实际 Agent 客户端示例 | `skill_creator` 创建 `MCPServerStreamableHttp` 指向 `/mcp`，并在 Agent 的 `mcp_servers` 中注册；README 指明 Agent 调用 `find_helpful_skills`、`list_skills` 等后端工具。 | **是，端到端消费者示例。**不过其示例配置的 Skill 源是本地 `mnt/skills`；“远程”体现在 Agent → 独立 HTTP MCP Skill 后端，并非默认配置从公网仓库拉取。 |

### 1. `skills-mcp`：远程 Skill gateway

- 官方 README 明确称其让 AI agents 在**无需先本地安装**的情况下，从 GitHub 或直接 HTTP URL 浏览和获取 Skills，并给出了 GitHub registry、HTTP registry、认证与缓存配置：[README](https://github.com/afriemann/skills-mcp/blob/dbbd17189348b4e8e84d3026d3e896b75e1d8290/README.md)。
- 服务端源码将 `list_skills` 与 `get_skill` 注册为 MCP tools：[server.py#L143-L196](https://github.com/afriemann/skills-mcp/blob/dbbd17189348b4e8e84d3026d3e896b75e1d8290/src/skills_mcp/server.py#L143-L196)。README 还定义 `skill://{registry}/{skill_path}` 供支持 resources 的宿主读取。
- GitHub adapter 通过 GitHub Contents/Git Trees API 递归查找 `SKILL.md`，并按所选 Skill 获取正文和其文件树：[github.py#L43-L154](https://github.com/afriemann/skills-mcp/blob/dbbd17189348b4e8e84d3026d3e896b75e1d8290/src/skills_mcp/registries/github.py#L43-L154)。HTTP adapter 则对 allow-list 配置中的 URL 发起 GET，返回单个 Skill 的内容：[http.py#L17-L64](https://github.com/afriemann/skills-mcp/blob/dbbd17189348b4e8e84d3026d3e896b75e1d8290/src/skills_mcp/registries/http.py#L17-L64)。
- 安全设计值得沿用：Agent 只能传 registry 名，不可传任意 URL；配置本身是 allow-list。README 还支持 ref 固定、环境变量取认证凭据和缓存。当前限制是 HTTP registry 只支持一个 `SKILL.md`，不支持伴随文件。

### 2. `claude-skills-mcp`：远程仓库预索引后用 MCP 取用

- README 将其定义为可由任意 MCP-compatible assistant 使用的 Skill 搜索／读取服务，列出三项 MCP tools 和 GitHub/local Skill sources；同时顶部声明该项目已停止托管维护：[README（固定提交）](https://github.com/K-Dense-AI/claude-skills-mcp/blob/72a7b502237cb3e697d3944be1b778498eed2d87/README.md)。
- MCP handler 注册 `find_helpful_skills`、`read_skill_document` 与 `list_skills`，其中第一项是语义搜索、第二项读取辅助文件：[mcp_handlers.py#L140-L233](https://github.com/K-Dense-AI/claude-skills-mcp/blob/72a7b502237cb3e697d3944be1b778498eed2d87/packages/backend/src/claude_skills_mcp_backend/mcp_handlers.py#L140-L233)。
- GitHub 加载函数把指定仓库下载为 tarball snapshot、查找 `SKILL.md`、解析正文并为辅助文件建立读取器：[skill_loader.py#L717-L840](https://github.com/K-Dense-AI/claude-skills-mcp/blob/72a7b502237cb3e697d3944be1b778498eed2d87/packages/backend/src/claude_skills_mcp_backend/skill_loader.py#L717-L840)。因此“远程获取”发生在 MCP server 的上游；Agent 从 MCP 取到的是检索结果和文档。

### 3. `mcp-skill-creator-agency`：Agent 接入远程 MCP Skill 后端

- README 要求先启动独立的 `claude-skills-mcp-backend` HTTP MCP server，随后运行 Agency；并描述 agent 会调用 `Claude_Skills.find_helpful_skills` 和 `Claude_Skills.list_skills`：[README（固定提交）](https://github.com/AlexFischman/mcp-skill-creator-agency/blob/b10155006157bb66884493c2b8f7967a27412e07/README.md)。
- Agent 定义直接使用 `agents.mcp.MCPServerStreamableHttp`，URL 为后端 `/mcp`，再加入 `mcp_servers`：[skill_creator.py#L1-L35](https://github.com/AlexFischman/mcp-skill-creator-agency/blob/b10155006157bb66884493c2b8f7967a27412e07/skill_creator/skill_creator.py#L1-L35)。这证明 Agent 端消费 MCP Skill 服务不是概念设想。

## 对落地方案的含义

若目标是“远程 Skill 可发现、可信且按需加载”，最贴近现状的协议设计是：

1. 以受控 MCP server 暴露 `list_skills`（名称、摘要、版本／内容哈希、来源）和 `get_skill`（`SKILL.md`、显式请求的辅助文件）；可同时提供 `skill://` resource template，供支持 resources 的宿主使用。
2. 将 registry/域名、发布者身份、允许的 ref/版本、最大下载量写在服务端 allow-list；不要让模型提交任意 URL。优先 pin commit/hash，校验内容哈希／签名，并针对脚本与附件设置审计和执行许可。
3. 在 Agent 宿主层实现“激活”策略：先仅加载 metadata，用户或模型选中后读取 `SKILL.md`，最后按需读取辅助文件。MCP 负责传输和发现，不应默认为远程脚本授予执行权。
4. 若只需要一次性的、参数化指令，可使用标准 MCP prompts；若需要包含脚本／资源且由宿主动态选取的目录型能力，应采用上述自定义 tool/resource 约定，并记录其并非跨客户端自动互操作的标准 Skill API。

## 局限

- 以上结论基于公开仓库在文中固定提交时的源码；未对各项目进行真实部署或安全审计。
- “MCP compatible”不等于每个客户端都支持 resources，亦不等于会把返回的 `SKILL.md` 注册为其本机的原生 Skill。应在目标 Agent 上做一次 `list_skills → get_skill → 使用内容完成任务` 的集成验证。
- 本调研未发现 MCP 官方规范或官方 SDK 提供通用的远程 Skill 安装／卸载／启用 API；这不是否定未来扩展，仅是当前固定版本规范的范围说明。
