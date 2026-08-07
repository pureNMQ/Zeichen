# Cognee 官方 MCP `improve` 实现核查（2026-08-07）

## 结论

Cognee 官方 MCP 的 `improve` **不是异步作业接口**。尽管 Python 函数本身是 `async`，它会在一次 MCP tool call 内 `await` 完整的 Cognee `/api/v1/improve` 调用；官方 MCP 没有暴露 `run_in_background`、没有返回 `job_id` / `pipeline_run_id`，也没有提供 improve 专用的取消或状态查询协议。

这正是 MCP 30 秒 deadline 不适配长时间蒸馏的原因：调用方必须一直等待，直到上游完成、报错，或由调用方/传输层超时。

本项目使用的镜像基线是 v1.4.1（`Dockerfile.cognee`）。将该 tag（commit `82bc3de`）与 2026-08-07 获取的官方 `main`（commit `38eece5`）比较后，以下五个相关文件均未变化：MCP server/client、`api/v1/improve/improve.py`、session lock、dataset lock。因此下面关于 MCP 同步行为和锁的结论同时适用于两者。

## MCP 工具的实际接口与调用链

| 层 | 实现 | 含义 |
| --- | --- | --- |
| MCP tool | `improve(dataset_name: str = None, session_ids: str = None)` | 仅两个参数；`session_ids` 为逗号分隔字符串。没有 `run_in_background`、deadline、取消或 job 查询参数。 |
| MCP → API client | `await cognee_client.improve(...)` | tool 调用同步等待 HTTP 响应，未创建后台 task。 |
| API client → Cognee API | POST `/api/v1/improve`，payload 只有 `dataset_name` 和可选 `session_ids` | 没有把 API 已支持的 `run_in_background` 字段透传出去。 |
| Cognee API | `run_in_background` 的 DTO 默认值为 `False` | 所以 MCP 实际总是走阻塞模式。 |

证据：

- [MCP tool 定义与直接 await（v1.4.1，server.py:1229-1273）](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee-mcp/src/server.py#L1229-L1273)
- [MCP API client 只发送 dataset_name/session_ids（v1.4.1，cognee_client.py:614-634）](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee-mcp/src/cognee_client.py#L614-L634)
- [HTTP `/v1/improve` 的 DTO：`run_in_background=False`（v1.4.1，router.py:22-35）](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/routers/get_improve_router.py#L22-L35)
- [路由把该字段原样交给核心 improve（v1.4.1，router.py:81-108）](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/routers/get_improve_router.py#L81-L108)

## 返回值：没有 job ID，且存在误报路径

MCP tool 并不把 Cognee 的原始 pipeline 结果返回给调用方。它只从字典读取可选的 `status`，缺失时默认写为 `completed`，然后返回一条 `TextContent`：`Improve completed (status=...). ...`。[server.py:1257-1269](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee-mcp/src/server.py#L1257-L1269)

因此：

- **没有**由官方 MCP 交给调用方的 job ID 或 pipeline run ID；
- **没有**可由该 `improve` tool 轮询的状态接口；
- 当核心 improve 因同 session 已在执行而返回 `{}` 时，MCP 的 `result.get("status", "completed")` 会把它包装成 `Improve completed (status=completed)`，即把“跳过/忙”误报为成功。

核心实现对此的证据是：[单 session 的 improve-lock 已被占用时记录 skipping 并 `return {}`（v1.4.1，improve.py:155-173）](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/improve.py#L155-L173)。

## 官方 API/SDK 本身有后台模式，但 MCP 未使用

核心 `cognee.improve` 的确接受 `run_in_background: bool = False`，[improve.py:38-95](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/improve.py#L38-L95)，并把它传给最后的 `memify` enrichment：[improve.py:238-271](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/improve.py#L238-L271)。

`memify` 的后台执行器会先推进 async generator 取得 started run info，之后通过 `asyncio.create_task` 执行剩余 pipeline，并返回按 dataset ID 映射的初始 run info：[pipeline_execution_mode.py:54-127](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/modules/pipelines/layers/pipeline_execution_mode.py#L54-L127)。其文档也明确说后台模式可用返回值内的 `pipeline_run_id` 监控：[memify.py（run_in_background 与返回值说明）](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/modules/memify/memify.py#L25-L83)。

但这不等于完整的 session-improve job：在 improve 的 session 流程中，feedback、session 持久化、trace、distill 等前置阶段仍在调用 `memify` 前被顺序 `await`；MCP 又完全没有办法设置后台模式或暴露其 run info。[improve.py:175-252](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/improve.py#L175-L252)

## 超时、取消与锁

上述 official MCP `improve` 路径中没有 `asyncio.timeout`、`asyncio.wait_for`、取消 endpoint 或 task owner/deadline；它依赖 `await` 自然返回。核心 improve 只在 `finally` 中释放 session improve lock：[improve.py:271-276](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/api/v1/improve/improve.py#L271-L276)。所以内部 await 若不返回，finally 也无法运行。

session improve lock 是进程内 `set[str]` 上的非阻塞 claim；没有 owner、TTL 或 stale-reclaim，持有时后续调用立即返回 false：[session_lock.py:63-99](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/infrastructure/locks/session_lock.py#L63-L99)。dataset lock 也只是进程内 `asyncio.Lock`，`async with` 无期限等候：[dataset_lock.py:1-12](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/infrastructure/locks/dataset_lock.py#L1-L12)、[dataset_lock.py:43-66](https://github.com/topoteretes/cognee/blob/82bc3de9062af26ebcac3d61343d7e1a4f577586/cognee/infrastructure/locks/dataset_lock.py#L43-L66)。

## 对 Zeichen 的结论

不能通过“模仿官方 MCP improve”解决 30 秒限制——官方实现本身就是同步等待，且会把 `{}` 误报为 completed。应继续采用 Zeichen 侧的持久化异步 job/worker：立即返回自身 `job_id`，状态只在实际完成后标记 `completed`，并把上游 `{}` 视为 `in_progress`/conflict；不要把 transport timeout 当成远端任务已停止。

