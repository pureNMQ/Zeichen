# 闲时需求自动接取调度器（idle-runner）

目标：闲时自动、串行地消耗 Zeichen 需求队列——**in_progress 优先（最近活跃在前），否则
backlog（最近活跃在前）**；`pending`（待确认）永不准入；每个需求由一个**全新的独立 ZCode
子代理**在一次独立会话中实施，完成一个、回写证据、回报结果，然后才开启下一个。

## 架构

```
cron / 任意 ZCode 会话                ZCode 会话（调度方）                Zeichen
────────────────────                ─────────────────────              ───────
python3 dispatch.py status   ──►     dispatch.py next ──出工单──►  派生全新子代理
（队列巡检，可选）                   （锁+防重，MCP over HTTP）        （按 WORKER_PROMPT 执行）
                                                                        │
                                     子代理完成 ◄── mark done/failed ◄──┘
                                     （调度方核实后再派下一个）
```

- `dispatch.py`：直连 Zeichen MCP 的**无会话 HTTP 端点**（URL 与令牌取自
  `~/.zcode/cli/config.json` 的 `zeichen` 服务器），不依赖任何 ZCode 会话即可选单。
  文件锁（`~/.local/state/zeichen-idle-runner/lock`）防并发；`state.json` 记录已处理需求
  （dispatched/done/failed），防止重复准入；工单落在 `tickets/`。
- `WORKER_PROMPT.md`：派生子代理时注入的执行协议（状态核实→实施→回写→mark）。
- 子代理安全边界：不 push、不部署；任务完成只置 verifying；证据必须回写 Zeichen 评论。

## 用法

```sh
python3 /srv/zeichen/scripts/idle-runner/dispatch.py next [--dry-run]   # 出下一张工单
python3 /srv/zeichen/scripts/idle-runner/dispatch.py status             # 看队列与处理记录
python3 /srv/zeichen/scripts/idle-runner/dispatch.py mark <REQ_ID> done|failed --note "..."
python3 /srv/zeichen/scripts/idle-runner/dispatch.py reset <REQ_ID>     # 重新准入
```

退出码：0 成功；1 队列空；2 锁占用；3 配置/MCP 错误；4 用法错误。
多项目时用 `ZEICHEN_PROJECT_ID` 指定项目。

## 已知限制（本机环境实测）

1. **本机没有可无头调用的 `zcode` CLI**：ZCode 以「桌面附加远程」模式运行，会话只能由
   桌面端开启。因此"派生新会话"这一步由**当前打开的 ZCode 会话**通过其 Agent 工具完成——
   调度链在会话存活期间推进；会话关闭后，下次打开任意会话跑 `next` 即可续链。
2. **模型固定为会话模型**：子代理继承当前会话的模型，无法在派生时指定 GLM 5.3 flash
   免费档；待 ZCode 支持子代理模型参数后可切换。
3. cron 只能做 `status`/`next` 巡检与出票，不能自己启动 ZCode 执行工单。

## 挂靠

本调度器自身是 Zeichen 需求 REQ 3e71f019（闲时需求自动接取调度器）的交付物。
