# Cognee #4309 状态复查（2026-08-13）

## 结论

[Cognee #4309](https://github.com/topoteretes/cognee/issues/4309) 已于 **2026-08-13 08:53:27 UTC**（北京时间 16:53:27）由维护者 `dexters1` 关闭，GitHub 的状态原因是 `completed`。不过，GitHub 的 issue 时间线、关联 PR/提交检索、最新发布版本和当前源码均**没有**显示该 issue 所建议的 stale-lock 回收或 `improve()` 总超时已合并。因此，这次关闭不能作为“官方已修复”的依据。

截至本次复查，官方给出的实质处理方向是：由调用方为本地 LLM 调用设置 timeout，使 pipeline 失败并通过既有 `finally` 释放锁；不是在 Cognee 内部增加 lock TTL/reclaim 或 improve 的全流程 deadline。

Zeichen 已上线的异步作业、状态查询、同会话去重和 `{}` 防误报仍应保留；升级至当前发布版并不能替代这些保护。

## GitHub 状态与时间线

| 时间（UTC） | 事件 | 证据与含义 |
| --- | --- | --- |
| 2026-08-02 03:02:04 | #4309 创建 | 报告单 session `improve()` 在内部 await 永不返回时，会永久持有进程内锁；后续调用返回 `{}`。见 [issue 正文](https://github.com/topoteretes/cognee/issues/4309)。 |
| 2026-08-02 10:27:08 | 维护者评论 | `dexters1` 询问具体 hang 原因，并建议“为 LLM calls 加 timeout，使 pipeline fail”。未承诺实现 Cognee 内部超时或 stale reclaim。见 [评论](https://github.com/topoteretes/cognee/issues/4309#issuecomment-5157176692)。 |
| 2026-08-08 17:11:30 | 交叉引用 | 时间线仅出现 [#4394](https://github.com/topoteretes/cognee/issues/4394)，其主题是跨进程的 dataset 并发写入，不是 #4309 的 session stale-lock 修复。 |
| 2026-08-13 08:53:27 | 关闭 | `dexters1` 将 issue 关闭（`completed`）；时间线没有 close comment、关联 PR、commit 或 release。见 [issue 时间线](https://github.com/topoteretes/cognee/issues/4309)。 |

本次使用 GitHub API/CLI 查询了 #4309 的正文、两条评论和完整 timeline，并检索仓库中引用 `4309` 的 PR 与提交；未发现关联修复 PR 或提交。

## 发布与源码核对

- 最新正式发布版为 [v1.4.2](https://github.com/topoteretes/cognee/releases/tag/v1.4.2)，发布时间 **2026-08-08 17:56:06 UTC**，早于 #4309 的关闭时间。
- 在 [v1.4.2 的 `session_lock.py`](https://github.com/topoteretes/cognee/blob/v1.4.2/cognee/infrastructure/locks/session_lock.py) 中，`_improving_sessions` 仍为 `set[str]`；没有 acquire 时间、TTL、owner-liveness 或 stale-reclaim 分支。
- 当前 [`main` 的 `session_lock.py`](https://github.com/topoteretes/cognee/blob/main/cognee/infrastructure/locks/session_lock.py) 仍使用相同的进程内 `set`，并明确说明其 scope 是单 worker FastAPI；没有 `COGNEE_IMPROVE_LOCK_TTL` 之类配置。
- 当前 [`main` 的 `improve.py`](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/improve/improve.py) 仍在获得单 session lock 后以 `try/finally` 释放锁，但没有 `asyncio.timeout` 或 `asyncio.wait_for` 包裹 improve 主体。因而“已抛异常”的泄漏路径会释放锁，而“await 永不返回”的路径仍不能自行到达 `finally`。

这也说明 v1.4.2 未包含 #4309 所提的两层修复：锁租约/过期回收，以及 improve 作业总超时。

## 对 Zeichen 的影响

1. 不应因为 #4309 已关闭就移除 Zeichen 侧防护，也不应将升级到 v1.4.2 视为问题已消失。
2. 当前方案仍正确：MCP 仅提交异步作业；Worker 使用有界等待；把 Cognee `{}` 解释为 `upstream_busy` 而非完成；保留可查询的 job 状态，避免 HTTP/MCP 超时被误报为蒸馏成功。
3. 如要进一步降低触发概率，可按维护者建议在本地 LLM/provider 层配置明确的连接、读取和总请求 timeout；但这只是缩小 hang 概率，不能提供 session stale-lock 的上游回收机制。
4. 后续仅在上游出现可审计的修复 PR/commit，且版本发布说明及对应 tag 源码确实包含 TTL/reclaim 或 improve deadline 后，再评估简化 Zeichen 的兼容层。

## 来源与范围

- [Issue #4309](https://github.com/topoteretes/cognee/issues/4309)（正文、状态、关闭时间、评论与 timeline；读取于 2026-08-13）
- [维护者评论](https://github.com/topoteretes/cognee/issues/4309#issuecomment-5157176692)（2026-08-02）
- [v1.4.2 release](https://github.com/topoteretes/cognee/releases/tag/v1.4.2)（2026-08-08）
- [v1.4.2 `session_lock.py`](https://github.com/topoteretes/cognee/blob/v1.4.2/cognee/infrastructure/locks/session_lock.py) 与 [当前 main `session_lock.py`](https://github.com/topoteretes/cognee/blob/main/cognee/infrastructure/locks/session_lock.py)
- [当前 main `improve.py`](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/improve/improve.py)

所有结论都基于 `topoteretes/cognee` 的 GitHub 一手资料；未把 issue 的 `completed` 状态推断为代码已发布。
