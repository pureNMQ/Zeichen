# 预设「标准模式 + zeichen MCP」— 本机 Windows DSH 安装说明

> 生成于 2026-10-07。本目录两个文件是完整预设，目标位置是**本机** DSH 的个人预设目录：
> `C:\Users\pureNMQ\.dsh\.agent-presets\zeichen-standard\`
> （远程服务器上的 dsh web 实例已直接安装同款预设，无需本操作。）

## 这是什么

在 DSH 自带的「标准模式」预设（v0.1.1-rc.2, `config/agent-presets/standard/`）完整组成之上，
追加一行 `@deepseek-ai/dsh-mcp-client`，接入 Zeichen(贼船) 的 MCP 服务：

- 传输：streamable HTTP，`https://www.mochigm.cn/mcp`（正规 CA 证书，MCP 白名单已含 `www.mochigm.cn:443`）
- 认证：Bearer API key（agent **mocha**，属主 pureNMQ —— 与 `~/.zcode/cli/config.json` 的 zeichen 服务器同一把）
- 工具：以 `mcp__zeichen__<name>` 形式注册，如 `mcp__zeichen__requirements.create`、`mcp__zeichen__docs.wiki.get`
- 超时：单次工具调用 190s（与旧配置一致；nginx 侧 `proxy_read_timeout 3600s`）

## 安装（PowerShell，在本机运行）

```powershell
$dst = "$env:USERPROFILE\.dsh\.agent-presets\zeichen-standard"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
# 从 DSH 会话里复制本目录两个文件的内容，分别保存为：
#   $dst\preset.yml
#   $dst\agent.cordis.yml
notepad $dst\preset.yml
notepad $dst\agent.cordis.yml
```

保存后回到 DSH 界面刷新会话页面，新建会话时预设列表即出现「标准模式 + zeichen MCP」。

## 注意事项

1. **key 为明文**：这是当前 MCP 接入方式的已知缺陷（见
   `research/dsh-plugin-replace-mcp-design-20261007.md` 问题 #1）。Rotate key 时需同步更新
   `agent.cordis.yml` 最后一行。
2. **旧 key 已失效**：远程 profile `cordis.patch.yml` 里原来的 `zc_PLcGsy…` 已被吊销（401），
   本预设用的是 `~/.zcode/cli/config.json` 里仍有效的 `zc_yDXOM…`。
3. 服务器重启/域名不可达时预设仍可加载（`failOnStartupError` 默认 false），只是 zeichen 工具缺失。
4. 若日后在 profile 层再全局加 `serverName: zeichen` 的 MCP 客户端，会与本预设冲突
   （serverName 需全局唯一），二选一。
