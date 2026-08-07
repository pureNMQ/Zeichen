# Cognee 记忆全流程（官方资料调研）

> 调研时间：2026-08-07。资料仅使用 Cognee 官方文档与官方 GitHub 仓库。本文把“记忆”分成**原始资料、图/向量长期记忆、会话短期记忆**三层，并区分当前的 v1.0 memory API 与仍可用的低层 API。

## 结论先行

最容易记住的主线是：

```text
资料/事件 ──add──> 可追溯的原始数据 ──cognify──> 图 + 向量长期记忆
                                         │
问题 ──search───────────────────────────┘──> 上下文/答案

会话事件 ──remember(session_id)──> session cache ──improve──> 长期图记忆
```

官方把现在面向“agent memory”的高级主线定义为 `remember → recall → improve → forget`；`add → cognify → search` 是可单独控制每一阶段的 legacy/低层构件。[Overview](https://docs.cognee.ai/core-concepts/overview)

## 一个贯穿例子：客服代理记住 Alice

假设系统收到两段资料：

```text
Alice 是客户 ACME 的采购负责人，偏好简洁的周报。
2026-07-20：ACME 的账单导出失败；已通过重建 SSO 映射解决。
```

### 1. 写入原始资料：`add`

```python
await cognee.add(
    [
        "Alice 是客户 ACME 的采购负责人，偏好简洁的周报。",
        "2026-07-20：ACME 的账单导出失败；已通过重建 SSO 映射解决。",
    ],
    dataset_name="support_memory",
    node_set=["customer_acme", "support"],
)
```

`add` 接收文本、文件、URL、二进制流或 `DataItem`，解析/摄取内容、记录元数据与权限，并把资料归入 dataset；其签名提供 `incremental_loading=True`，用于避免重复摄取已加载的资料。[add API](https://docs.cognee.ai/python-api/add) [实现](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/add/add.py)

此时不要把它误解成“已经可用的语义记忆”：资料已进入可追溯存储，但实体关系、向量和摘要尚未由下一步建立。

### 2. 认知化：`cognify`

```python
await cognee.cognify(datasets="support_memory")
```

`cognify` 会对已摄取的资料分类、分块、抽取实体及关系、建立知识图谱、生成 embeddings 和摘要。上例大致会形成 `Alice —负责采购→ ACME`、`Alice —偏好→ 简洁周报`、`账单导出失败 —由→ 重建 SSO 映射解决` 等节点/边（具体抽取结果由模型与提示词决定，不能把示意关系当作确定输出）。它支持 `graph_model`/`custom_prompt` 来约束抽取结构，`temporal_cognify=True` 做时间感知抽取。[cognify API](https://docs.cognee.ai/python-api/cognify) [实现](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/cognify/cognify.py)

`node_set` 由写入时的标签，在 cognify 后成为图中的一等节点；所以它既可按客户、项目或工作流组织资料，也可在检索时缩小子图。[官方 Cognee skill](https://github.com/topoteretes/cognee/blob/main/cognee/skill.md)

### 3. 召回：`search`

```python
from cognee import SearchType

answer = await cognee.search(
    query_text="如何给 Alice 写账单问题的跟进？",
    query_type=SearchType.GRAPH_COMPLETION,
    datasets="support_memory",
    node_name=["customer_acme", "support"],
)
```

`GRAPH_COMPLETION`（默认）是图感知问答；`RAG_COMPLETION` 只基于文档 chunks；`CHUNKS` 直接返回相似片段，适合需要原文/引用且不希望生成的场景；另有摘要、Cypher、时序等类型。图问答和 RAG completion 需要 LLM，而 `CHUNKS` 是纯向量相似度检索。检索可限定 dataset、权限可见范围和 NodeSet，默认 `top_k=15`。[search API](https://docs.cognee.ai/python-api/search) [SearchType](https://docs.cognee.ai/python-api/search-type) [实现](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/search/search.py)

## 高级记忆 API：短期会话如何变成长期经验

若代理正在一次实时会话中工作，优先使用 `remember`/`recall`：

```python
# 先快速写进该用户的短期会话记忆
await cognee.remember(
    "Alice 说：此次回复请不要超过三条要点。",
    dataset="support_memory",
    session_id="ticket-847",
)

# 同一 session 可先命中这条新上下文；需要时再回退到长期图
result = await cognee.recall(
    "本次怎样回复 Alice？", dataset="support_memory", session_id="ticket-847"
)

# 需要立即固化时显式执行；也可由 remember 的默认自我改进流程后台执行
await cognee.improve(dataset="support_memory", session_ids=["ticket-847"])
```

- 无 `session_id` 的 `remember`：摄取、分块、实体/关系抽取、图/向量/摘要，并默认接续 `improve`，即直接走永久记忆路径。
- 有 `session_id` 的 `remember`：先以 `(user, session)` 为边界写 session cache；默认 `self_improvement=True` 会后台桥接到长期图。关掉它时，调用方需在合适的时机 `improve(..., session_ids=...)`。
- `recall`：有会话且未明确指定长期检索时，先按关键词在会话的 question/context/answer 中查找，未命中再走图；`only_context=True` 只给检索上下文，不产生最终回答/新的会话 Q&A。
- `improve`：不是首次建图的替身；它在现有图上增加用于检索的派生结构（如 triplet embeddings、可选 global context index），并可将会话 Q&A、trace 和反馈蒸馏/持久化为长期记忆。

来源：[remember](https://docs.cognee.ai/core-concepts/main-operations/remember)、[recall](https://docs.cognee.ai/core-concepts/main-operations/recall)、[improve](https://docs.cognee.ai/core-concepts/main-operations/improve)。

## 三类持久化与“记住了什么”

| 层 | 保存内容 | 主要用途 |
| --- | --- | --- |
| 关系型存储 | dataset、原始文档、chunks、provenance | 可追溯、增量、更新 |
| 向量库 | 文档/chunk/图元素的 embeddings | 语义召回 |
| 图数据库 | 实体、关系、NodeSet 和关联 | 多跳关系与图上下文 |
| session cache | 用户+会话的短期 Q&A/context/trace | 当前任务连续性 |

前三层是长期资料/知识记忆；session cache 是短期层，是否/何时提升为长期记忆取决于 `improve` 策略。官方概览明确列出关系库、向量库和图数据库三类持久化；高级流程的 session 行为见 remember/recall 文档。[Overview](https://docs.cognee.ai/core-concepts/overview)

## 更新、重建、遗忘

### 精确更新一条来源

```python
await cognee.update(data_id=old_id, data="修订后的资料", dataset_id=dataset_id)
```

源码显示 `update` 的顺序是：删除旧 data ID → `add` 新数据 → 对该 dataset `cognify`。因此它不是原地改某一个图属性，而是按来源重建该条资料的派生记忆；其他资料仍在。默认 `incremental_loading=True`，设为 `False` 会让 cognify 不走增量路径。[update API](https://docs.cognee.ai/python-api/update) [实现](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/update/update.py)

### 保留原文、重建全部派生记忆

```python
await cognee.forget(dataset="support_memory", memory_only=True)
await cognee.cognify(datasets="support_memory")
```

`memory_only=True` 的语义是保留原始资料与 dataset，删除图/向量等记忆层并重置管线状态，随后可重新 cognify；`forget` 本身不调用 LLM 或 embedding。[forget](https://docs.cognee.ai/core-concepts/main-operations/forget)

## 实践 caveats

1. `cognify`/`remember` 的异步后台模式中，新资料未完成索引前可能只能获得部分或旧结果；应查询 dataset/pipeline status 再承诺“已记住”。
2. 内嵌 SQLite/Kuzu/LanceDB 默认适于单进程；多进程或多 agent 部署应使用外部存储并以一个 Cognee service 协调。文件/URL 用 session 型 remember 时按纯文本处理，不能期待完整文件解析。
3. dataset 是组织、权限和检索边界；NodeSet 是同一 dataset 内更轻的逻辑分组，二者不是同一层级。
4. `GRAPH_COMPLETION` 会使用 LLM，`CHUNKS` 不会；要做可复核检索时先取 chunks/上下文，再由应用自行生成答案往往更可控。

前两项见 [remember](https://docs.cognee.ai/core-concepts/main-operations/remember) 与 [recall](https://docs.cognee.ai/core-concepts/main-operations/recall)；检索类型限制见 [search](https://docs.cognee.ai/python-api/search)。

## 版本界限

本笔记以 2026-08-07 可访问的官方文档和 `main` 分支源码为准。官方最新 GitHub release 当时为 **v1.4.1.dev0**（2026-08-05），属于 development snapshot；仓库同时公开 v1 低层 API 与较新的 memory-oriented API，方法签名、默认值和搜索类型都可能随发布版本变化。接入时请固定安装版本，并以对应 tag 的文档/源码复核。[官方 release](https://github.com/topoteretes/cognee/releases/tag/v1.4.1.dev0) [导出 API](https://github.com/topoteretes/cognee/blob/main/cognee/__init__.py)
