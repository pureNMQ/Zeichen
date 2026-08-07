# Cognee GitHub：锁、挂起与超时调查（2026-08-07）

## 结论

在官方仓库 `topoteretes/cognee` 中，已经有与本次现象直接对应的公开 issue。对固定发布版 [v1.4.1](https://github.com/topoteretes/cognee/releases/tag/v1.4.1) 的源码核对表明：它包含「异常抛出时释放 session improve 锁」的修复，但**仍没有** improve 锁的租约/TTL、拥有者存活检测或整条 improve 流程的超时；dataset lock 也仍是进程内、无限期等待的 `asyncio.Lock`。因此，一个未返回的 pipeline await 仍可造成同 session 的 improve 永久返回 `{}`，并使等待同 dataset lock 的工作一直处于 `STARTED`。

这不是推测：发布后创建且仍开放的 [#4309](https://github.com/topoteretes/cognee/issues/4309) 报告了完全相同的 stale improve-lock 情形；[#4326](https://github.com/topoteretes/cognee/issues/4326) 同样承认 PipelineRun 没有可用于区分“仍在工作”和“已停滞”的 liveness 信号。

## 与本次复现的直接关联

| 官方条目 | 状态（截至 2026-08-07） | 与本次问题的关系 |
| --- | --- | --- |
| [Issue #4309 — `improve()` session lock has no stale-reclaim path](https://github.com/topoteretes/cognee/issues/4309) | Open；2026-08-02 创建（在 v1.4.1 发布后） | 明确描述：单 session improve 以进程内 `set` 持锁；若内部 await 永不返回，`finally` 永远到不了；后续调用记录 *already being improved, skipping* 并返回 `{}`。这与本次 session improve 锁级联阻塞一致。作者建议 TTL 回收和对 improve 主体施加超时。 |
| [Issue #3313 — improve session lock leaked on stage failure](https://github.com/topoteretes/cognee/issues/3313) / [PR #3317](https://github.com/topoteretes/cognee/pull/3317) | Closed / merged；2026-06-23 合入 | 修的是“阶段**抛异常**”路径，改为 `try/finally`。关联提交 [0419609](https://github.com/topoteretes/cognee/commit/04196099cfce5fce48e3413e591aa1f0d7a60154)。它不能处理本次“await 永不返回”的路径；#4309 也明确区分了两者。 |
| [Issue #4326 — Record pipeline run liveness so stalled background runs are detectable](https://github.com/topoteretes/cognee/issues/4326) | Open；2026-08-03 创建 | 指出 `PipelineRun` 只有 `created_at` 和 status，六小时停滞与长期正常运行无法从外部区分；建议每完成 task 更新 heartbeat。正对应本次遗留 `DATASET_PROCESSING_STARTED` 却无终态的诊断盲区。 |
| [PR #4166 — isolate background dataset failures](https://github.com/topoteretes/cognee/pull/4166) | Open、未合并 | 针对后台 pipeline supervisor 异常后，dataset 仍停在 `STARTED`、后台任务未关闭的情形。它和 #4326 一起说明 upstream 正在处理但尚未发布该类作业恢复/状态缺口。 |
| [PR #4167 — lock datasets across workers](https://github.com/topoteretes/cognee/pull/4167) | Open、未合并 | PR 描述当前 per-dataset asyncio registry 仅一个 Python 进程有效，且 registry 会永久保留每个 dataset 的 lock；拟补跨 worker 锁和本地 reference-count 清理。它解决多 worker 竞争/资源增长，**不等同于**为挂住的持锁任务增加 timeout 或 stale reclaim。 |

## 1.4.1 源码核对

所有链接都固定到 [v1.4.1 tag](https://github.com/topoteretes/cognee/tree/v1.4.1)，而非当前 `main`。

### Improve 锁：异常会释放，挂住不会释放

- [session_lock.py:72-99](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/locks/session_lock.py#L72-L99) 将 `_improving_sessions` 定义为 `set[str]`。取得锁只是原子 check-and-add；没有时间戳、owner、TTL 或回收分支。
- [improve.py:159-173](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/api/v1/improve/improve.py#L159-L173) 对单一 `session_id` 获取该 claim；若已存在则记录 `skipping` 并 `return {}`。这说明 `{}` 是竞争/占用信号，而非实际完成的 improve 结果。
- [improve.py:175-276](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/api/v1/improve/improve.py#L175-L276) 的 `finally` 包裹了 bridge、memify 和后续阶段，故 #3313 的“已抛异常”泄漏已经修复；但这里没有 `asyncio.timeout` / `wait_for`。如果某个 `await` 永不结束，执行不会离开 `try`，`finally` 就不会执行。

### Dataset 锁：进程内、无限期等待

- [dataset_lock.py:1-12](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/locks/dataset_lock.py#L1-L12) 的模块注释明确声明只在进程内生效，不保护多进程/多 worker。
- [dataset_lock.py:21-40](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/locks/dataset_lock.py#L21-L40) 使用按 dataset ID 永久缓存的 `dict[UUID, asyncio.Lock]`。
- [dataset_lock.py:43-66](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/locks/dataset_lock.py#L43-L66) 以 `async with await get_dataset_lock(dataset_id)` 无限等待；没有获取 deadline、任务取消、持锁者识别或看门狗。`finally` 只在已进入临界区后重置 `ContextVar`，不能打断仍在等待锁的调用。

### Pipeline run 状态不是活跃度或作业控制协议

- [PipelineRun.py:8-27](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/modules/pipelines/models/PipelineRun.py#L8-L27) 只有 `INITIATED`、`STARTED`、`COMPLETED`、`ERRORED` 四种状态，模型没有 `updated_at`、heartbeat、worker/task owner、deadline 或 cancellation 状态。
- [log_pipeline_run_start.py:9-33](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/modules/pipelines/operations/log_pipeline_run_start.py#L9-L33) 新增一条 `STARTED` 记录；[complete](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/modules/pipelines/operations/log_pipeline_run_complete.py#L9-L30) 与 [error](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/modules/pipelines/operations/log_pipeline_run_error.py#L9-L36) 则分别新增终态记录。若协程卡住而不抛错，就不会有终态写入。

## 超时与取消：已有局部修补，未覆盖根因

| 官方条目 | 状态 | 可得出的边界 |
| --- | --- | --- |
| [Issue #4049 — CancelledError retry storm in cognify pipeline when tasks timeout](https://github.com/topoteretes/cognee/issues/4049) | Closed | 报告 pipeline 的 `gather()` 缺少 timeout/取消处理，并可能造成重试风暴或长期挂起。维护者在评论中把修复指向 #4051。该 issue 针对取消后的重试扩大，并非 stale dataset/session lock 回收。 |
| [PR #4051 — stop cancelled retry for LLM/Embedding calls](https://github.com/topoteretes/cognee/pull/4051) | Closed、已合并（2026-07-14，早于 v1.4.1） | 仅让 LLM/embedding 在 `CancelledError` 时不再重试；标题和说明均是“stop cancelled retry”。它需要上层先发生 cancellation，未提供 improve 作业 timeout/取消端点，也没有锁租约。 |
| [Issue #2995 — universal wall-clock timeout for LLM completion calls](https://github.com/topoteretes/cognee/issues/2995) | Closed | 问题说明承认部分 provider 路径没有统一 wall-clock 上限，并特别指出外层 `asyncio.wait_for` 未必能在 deadline 干净取消 instructor 重试循环。即使单次 LLM timeout 已有局部改进，仍不能把“只加一层 wait_for”当作完整安全方案。 |

## 旧的相关并发问题（佐证，不应与当前根因混同）

- [Issue #2717 — SQLite deadlock during `cognify()`](https://github.com/topoteretes/cognee/issues/2717) 已关闭，讨论的是 SQLite 多写入并发导致的 `database is locked`，与本次“一个 in-process asyncio dataset lock 被未返回任务持有”不同。
- [Issue #3766 — delete while dataset pipeline is processing returns 500](https://github.com/topoteretes/cognee/issues/3766) 仍开放，使用 `DATASET_PROCESSING_STARTED` 作为可观察状态并要求改成可重试的 409/423。这佐证 processing 状态已成为外部并发控制信号，但该 issue 不提供停滞作业的恢复机制。

## 对修复决策的影响

1. **升级到 1.4.1 不能解决本次卡死。** 它已经有 #3313 的 `finally`，而 #4309 是在该版本发布后报告的尚未解决缺口。
2. **不要释放锁却让原协程继续运行。** 官方 #4309 的 TTL 建议能限制 session lock 的影响面，但对 dataset 写入还必须先取消/隔离旧 owner，或使用带 fencing token 的租约；否则旧任务恢复会和重试任务并发改写同一 dataset。
3. **应把改善流程做成可监控作业。** 至少记录 run owner、开始/heartbeat/结束时间、阶段、deadline、`timed_out`/`cancelled` 终态；先可靠取消任务，再由 `finally` 释放锁。#4326 的 heartbeat 建议可作为监控层基础。
4. **Zeichen 仍应做外围保护。** 将 HTTP 超时与“Cognee 作业已取消且失败”区分；收到 `{}` 时显示 `in_progress/conflict`，不记录为 improve 成功，也不假设远端已停止。

## #4309 的频率、复发与负载证据（2026-08-07 补查）

结论：[#4309 正文](https://github.com/topoteretes/cognee/issues/4309) 提供的是**单个长期运行生产进程的观测**，不是跨部署的发生率或可外推的并发阈值。

- 触发器的原话是 “**Occasional** pydantic `union_tag_not_found` validation failures”；随后称这些 failure “**rare events**”。但没有给出该失败的次数、分母、每小时概率或并发量。
- 唯一的明确试验数字是“4 local models 5x each … **20/20 passes**”。它测的是 `LLMGateway.acreate_structured_output` 对 schema 的通过情况，**不是** improve hang 的复现率，不能解释为 20 次 improve 均不会/会挂起。
- 生产复发的原话是：服务器以 session auto-improve 和 local LLM 运行“**for hours**”，一个 improve “**eventually hangs**”；重启后“**re-wedges within hours when another improve run hangs**”。这确认该报告者观察到了重复发生，却没有更精确的频率或工作负载（session 数、请求率、并发数）。
- 该次事故的计数是：**26** 个 distinct `session_id` 永久锁住、单一日志文件 **2,844** 行 `already being improved, skipping`，其中约 **1,480** 行位于单个 **40 分钟**窗口。它量化的是锁中毒后的自动重试放大，不是最初 hang 的发生率。
- 同一正文记录 dataset 在 `DATASET_PROCESSING_INITIATED` 冻结数小时、`recall` **240s** 超时、`/health` 约 **4ms**。这是单次事故的症状/时延，不是吞吐或并发基准。
- 截至该日的两条评论没有补充统计：一条 GitHub Actions 机器人要求最小复现；另一条维护者 [@dexters1 的评论](https://github.com/topoteretes/cognee/issues/4309#issuecomment-5157176692) 询问“**How does the improve hang?**”并建议为 LLM 调用加 timeout。没有维护者确认频率、SLO、并发上限或已复现实验。

因此可引用的严谨表述是：“#4309 证明该设计可被罕见的未返回 await 转化为长期、可反复出现的 session lock 中毒；该 issue 没有提供可泛化的 hang 发生率、负载阈值或并发阈值。”

## 来源与检索范围

- 仓库：[topoteretes/cognee](https://github.com/topoteretes/cognee)。
- 检索了该官方仓库的 issues、pull requests、release/tag，以及上述固定 tag 源码；未发现另一个官方 Cognee 仓库中有更直接、已合并的 stale improve-lock 或 pipeline liveness 修复。
- 状态与时间为 2026-08-07 的 GitHub API 读取结果。Issue 内容是报告者陈述；“1.4.1 仍存在相应设计缺口”的结论另由固定 tag 源码逐项核对。
