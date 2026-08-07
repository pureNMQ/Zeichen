# Cognee 会话蒸馏超时与锁不释放调查

> 调查日期：2026-08-07（运行日志为容器 UTC 时间；页面测试会话 ID 含本地时间 `memory-e2e-20260807-1429`）。
>
> 范围：只调查 Zeichen 调用的 Cognee `POST /api/v1/improve`。本文不修改应用、容器或测试数据。结论基于当前工作区代码、正在运行的 `zeichen-cognee-1` 容器源码与其标准输出日志；没有把推断写成已证实事实。

## 结论摘要

测试会话 `memory-e2e-20260807-1429` 的首次蒸馏没有在 Zeichen 的 **30 秒客户端 HTTP 超时**内完成；此后同一会话的蒸馏请求被 Cognee 以 HTTP 200 和空对象 `{}` 跳过。后者不是蒸馏完成：Cognee 日志明确记录 `already being improved, skipping`，而源码规定竞争锁失败时直接返回 `{}`。

锁是 Cognee 单 worker 进程内的 `set[str]`，没有到期时间（TTL）、租约或后台清理。它只在首次 `improve()` 协程返回或抛出后执行 `finally` 才释放。因此无法给出“卡住 N 分钟会自动恢复”的时间；正常完成、异常退出或进程重启才是已证实的恢复条件。当前证据尚不能定位 `apply_feedback_weights_pipeline` 内部究竟在等待哪一个子操作，需要在运行中抓取协程栈或增加阶段日志。

## 症状与影响

| 现象 | 已观察的影响 | 证据 |
| --- | --- | --- |
| 首次 `improve` 超过 30 秒仍未响应 | Zeichen 操作端超时，用户无法确认蒸馏是否完成；长期记忆未出现本次测试内容。 | `backend/app/config.py:29-30` 将 Cognee 超时设为 `30.0`；`backend/app/services/cognee.py:105` 以该值传入 `urlopen`。测试运行观察记录为首次蒸馏 30 秒超时。 |
| 同一会话后续请求很快返回 HTTP 200 | 调用方可能把空结果误认为成功并写入“蒸馏”活动；实际没有执行新的蒸馏。 | 容器日志 06:38:08、06:38:37、06:38:59（UTC）均为 `already being improved, skipping`，随后记录 `POST /api/v1/improve ... 200`；Cognee `improve.py:167-173` 在锁失败时 `return {}`。Zeichen `memory.py:163-169` 未检查结果是否为空便记录活动并提交。 |
| 同一会话无法重试 | 一次挂起会话会持续占用该会话的蒸馏入口；会话缓存仍可读取，但不能再次发起实际蒸馏。 | `session_lock.py:72-99` 只有进程内集合与 acquire/release，无 TTL；日志的三次 skip 直接证明锁仍被持有。 |

## 复现步骤与时间线

### 复现路径

1. 以 `editor`/`owner` 身份向项目 Agent 会话写入一条缓存内容；Zeichen 将其包装为 Cognee 的 typed QA entry（`backend/app/services/cognee.py:141-166`）。
2. 在会话详情执行“蒸馏”，调用 `memory.improve()`；它先检查项目编辑权限、按项目/Agent 生成受限 session ID，再调用 `CogneeClient.improve()`（`backend/app/services/memory.py:155-169`）。
3. 客户端向 `POST /api/v1/improve` 提交 `{ "datasetId": ..., "sessionIds": [session] }`（`backend/app/services/cognee.py:173-176`）。
4. 本次会话的首次请求在 30 秒客户端超时；对同一 session 重试，服务日志改为“正在蒸馏，跳过”，HTTP 仍为 200。

### 已保留的运行时间线

| 时间（UTC） | 观察 | 来源 |
| --- | --- | --- |
| 06:33:54.062 | Cognee 对标记 `ZEICHEN_MEMORY_E2E_20260807_1429` 的 recall 路由为 `GRAPH_COMPLETION`。 | `docker logs zeichen-cognee-1` 当次调查输出：`query_router: ... default=GRAPH_COMPLETION`。 |
| 首次 improve 后超过 30 秒 | 调用端超时，未得到完成结果。 | 当次端到端测试运行观察；30 秒上限由 Zeichen 配置和 `urlopen` 调用佐证（见上节）。 |
| 06:38:08.290 | 对该 session 的重试被记录为 `already being improved, skipping`。 | 容器日志。 |
| 06:38:37.450、06:38:59.458 | 再两次重试仍被跳过；对应 `POST /api/v1/improve` 均最终日志为 HTTP 200。 | 容器日志。 |
| 调查时 | 容器 `zeichen-cognee-1` 状态为 `Up`，镜像为 `zeichen-cognee:1.4.1-fastembed`。 | `docker compose ps` 运行观察。 |

对照证据：同一容器在 02:12:34、02:12:55、02:13:34 依次记录了另一会话的 `feedback weights applied`、`session Q&A persisted` 与 `distilled session ... status=completed documents=1`。这说明此环境曾成功完成完整链路，不能仅凭本次现象归因于 DeepSeek 账户或一般网络不可用；但它**不**证明本次卡住的具体子依赖。

## 代码与运行配置证据

### Zeichen：同步等待 30 秒，但不会取消服务端任务

- `backend/app/config.py:29-30`：默认 `COGNEE_BASE_URL=http://localhost:8000/api/v1`，`cognee_timeout_seconds=30.0`。
- `backend/app/services/cognee.py:94-115`：所有 JSON 请求均通过 `urllib.request.urlopen(request, timeout=self.timeout)` 发出，并在读取响应体时才返回；`improve()` 未设置服务端取消、任务 ID 或轮询机制（同文件 `173-176`）。
- `backend/app/services/memory.py:163-169`：即使 Cognee 返回 `{}`，当前代码仍记录 `memory_improve` 活动并 `commit()`，没有把“已跳过”映射为失败、冲突或进行中。

因此 30 秒是 Zeichen 对 HTTP 等待的上限，并非 Cognee 蒸馏协程的执行截止时间。客户端放弃等待不能从这些调用代码推导出对服务端请求协程的取消；当前协议也未实现显式取消接口。

### Cognee：锁的范围、返回语义和释放路径

- 当前容器镜像由仓库 `Dockerfile.cognee:1` 固定为 `cognee/cognee:1.4.1`；`docker-compose.yml` 将该镜像构建为 `zeichen-cognee:1.4.1-fastembed`。
- 容器内 `/app/cognee/infrastructure/locks/session_lock.py:1-19` 的模块注释明确声明为 “in-process asyncio registry”，且适用 “single-worker FastAPI”。
- 同文件 `72-73` 定义 `_improving_sessions: set[str]` 和进程内 `asyncio.Lock`；`76-91` 只做原子 check-and-add；`94-99` 只做 `discard`。该实现没有时间戳、TTL、租约所有者、心跳或清理协程。
- 容器内 `/app/cognee/api/v1/improve/improve.py:159-173`：单一 `session_id` 先申请锁；申请失败写入 `already being improved, skipping` 并 `return {}`。
- 同文件 `175-271`：成功申请后执行桥接、会话持久化/蒸馏和 `memify`；`272-276` 的 `finally` 才调用 `release_improve_lock()`。所以首次调用未离开 `try` 时，锁不会释放；无论正常返回还是异常传播，只要协程实际退出，`finally` 会运行。

### 已知等待位置与不确定边界

锁取得后的第一项主要工作是 `_bridge_sessions(...)`（`improve.py:175-185`）。该函数首先 await `apply_feedback_weights_pipeline(...)`（`300-331`），成功后才记录 `feedback weights applied`；随后才会 await 会话 Q&A 持久化（`335-346`）。本次有关 session 的日志中没有这两条“完成”日志，也没有 `distilled session` 成功/失败日志。

这将阻塞点**收敛到**：取得锁之后、首次阶段完成日志之前，最靠前的可等待调用是 `apply_feedback_weights_pipeline`。但没有 Python 协程栈、下游请求日志或该 pipeline 的细粒度日志，不能严格断言卡在该 pipeline 的哪个子调用，也不能排除在进入该调用前的导入/调度处等待。报告不把它归因为模型调用；现有日志不足以证明是否已经向模型供应商发起了请求。

## 恢复语义与 Gunicorn 30000 秒

### 何时释放 / 是否会自动恢复

已证实的释放条件：

1. 首次 `improve()` 协程正常完成并返回；
2. 首次协程在 `try` 内抛出异常并退出（`finally` 执行）；
3. Cognee worker/容器进程重启，进程内 `_improving_sessions` 集合被清空。

未实现、因此不能依赖的机制：锁 TTL、定时回收、心跳、基于请求端断开的自动释放、对“跳过”会话的自动重试。故“卡住多久会恢复”的正确答案是：**没有固定自动恢复时长**；只能等待原协程退出，或通过受控重启清除进程内状态。

### `-t 30000` 的准确含义

容器 `/app/entrypoint.sh:51,53,56` 以 Gunicorn `-w 1 -k uvicorn.workers.UvicornWorker -t 30000` 启动服务；运行时 `/app/.venv/bin/gunicorn --help` 对 `--timeout` 的原文为：`Workers silent for more than this many seconds are killed and restarted.` 因而 `30000` 是约 **8 小时 20 分钟**的“worker 静默”阈值，而不是 `/improve` 的 30,000 秒业务 SLA、锁租约或请求必定被取消的计时器。

如果 worker 确实连续静默超过该阈值，重启会清空进程内锁；但这不是可预测的恢复承诺（取决于 Gunicorn 对该 worker 的静默判定及进程是否仍在存活）。容器内 Gunicorn 的 `arbiter.py:488-507` 仅在距 worker 上次 `notify` 超过 timeout 时发出终止信号；活跃的事件循环可继续 notify。因此不能把该参数当作请求硬截止或锁 TTL。本次容器仍为 `Up`，不能把 Gunicorn 参数当作短时间自愈方案。

## 修复建议（未实施）

优先级按先减少“假成功”和不可恢复阻塞、再定位底层耗时排列。

1. **Zeichen 立即防误报**：把 `/improve` 的空对象 `{}` 识别为“未执行/已有任务进行中”，返回明确的 409 或 202+任务状态，不写成功活动；在 `backend/app/services/memory.py` 的 `client.improve()` 结果后实现该判定。
2. **显式任务状态**：为一次蒸馏记录 request ID、session、开始/结束时间、当前阶段、结果和错误；前端展示“进行中/失败/已完成”，而非仅用同步 HTTP 成败判断。可由 Zeichen 先实现，避免 UI 把 HTTP 200 的 `{}` 当成功。
3. **Cognee 锁可恢复化**：将进程内集合改为带 owner 与过期时间的租约（单 worker 也应有 watchdog），或使用共享 Redis/数据库锁；超时前续租，任务终止/异常时释放。多 worker 场景必须采用进程外锁，容器源码的 `session_lock.py:17-19` 也明确提出 SQL advisory lock 或 Redis SETNX。
4. **阶段可观测性与可取消性**：在 `try_acquire`、`_bridge_sessions` 的每个 await 前后记录 session、阶段、耗时和异常堆栈；为长阶段设置业务 deadline，并在超时后取消/标记失败、释放锁。对当前已卡住实例，先抓 worker Python 协程栈再决定是否重启，避免丢失唯一定位证据。
5. **分离请求超时和作业超时**：若蒸馏本就允许超过 30 秒，改为异步提交/轮询，客户端超时只影响等待；同时设置一个明确小于 Gunicorn 30000 秒的作业 deadline。不要仅增大 `cognee_timeout_seconds`，否则仍会掩盖无 TTL 的锁问题。

## 验收标准

修复应至少通过以下可自动化验证：

1. 正常单会话蒸馏完成后，返回非空的明确完成状态，长期记忆可见，锁已释放；立即再次蒸馏不返回“仍在进行中”。
2. 人为让第一阶段超过作业 deadline：调用方在规定时间得到 `failed`/`timed_out` 状态及 request ID；锁在受控超时后释放，重试会真正执行而非返回 `{}`。
3. 并发两次同 session 蒸馏：只有一个作业执行；另一个得到可识别的 `in_progress`（而不是 HTTP 200 `{}`），且不会记录为成功活动。
4. 异常路径（pipeline 抛错、LLM/图存储不可用、客户端断开）均保留阶段/错误日志，并验证锁释放或由租约超时回收。
5. 重启恢复测试：在任务中断后重启 worker/容器，旧进程内锁不再阻塞；持久化任务状态不会误报为已完成。
6. 前端与 API 集成测试：仅在状态为 `completed` 时显示成功通知；`in_progress`、`failed`、`timed_out` 均使用可关闭错误/状态通知，符合仓库 `AGENTS.md` 对非模态失败反馈的要求。

## 证据清单与限制

| 类型 | 一手来源 |
| --- | --- |
| Zeichen 代码 | `backend/app/config.py`、`backend/app/services/cognee.py`、`backend/app/services/memory.py` |
| 容器构建与配置 | `Dockerfile.cognee`、`docker-compose.yml`；运行容器 `/app/entrypoint.sh` |
| Cognee 已运行源码 | `zeichen-cognee-1:/app/cognee/infrastructure/locks/session_lock.py`、`/app/cognee/api/v1/improve/improve.py` |
| 运行观察 | `docker compose ps`、`docker logs zeichen-cognee-1`（2026-08-07 当次调查） |
| 运行时参数说明 | `zeichen-cognee-1:/app/.venv/bin/gunicorn --help` |

容器日志没有提供首次请求的完整开始/结束与 Python 栈，且当前应用没有任务记录。因此本文不能给出底层等待对象、确切开始时刻或一个可靠的自动恢复倒计时。这些正是建议中优先补齐的可观测性数据。
