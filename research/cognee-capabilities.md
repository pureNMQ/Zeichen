# Cognee 能力与多主体记忆隔离 — 调研结果

> 调研对象：本地安装 cognee **1.4.0**（`D:\Cognee\.venv\Lib\site-packages\cognee\`，运行时日志确认 `cognee_version=1.4.0`）
> 数据源：本地安装源码（文件路径+行号）、官方文档 https://docs.cognee.ai/（页面 URL）、本地实例实际数据（SQLite 探测）。
> 注：本地安装版本号日志输出于 `D:\Cognee\.venv\Lib\site-packages\cognee\version.py` 的调用结果（`import cognee; cognee.__version__` → 1.4.0）。

---

## 1. REST API 面（端点清单、参数、限制）

FastAPI app 定义于 `cognee/api/client.py`，全部路由注册于 `client.py:203-311`。鉴权方案：Bearer JWT + `X-Api-Key` 头（`client.py:143-148`）；`REQUIRE_AUTHENTICATION=true` 时全局强制鉴权（`client.py:150-160`）。

### 1.1 v1 记忆操作（本 spec 最相关）

| 方法/路径 | 请求 | 关键参数（默认值） | 来源 |
|---|---|---|---|
| `POST /api/v1/remember` | multipart/form-data（文件上传，**不接受 JSON 字符串 data**） | `data`(List[UploadFile], 必填)、`datasetName`/`datasetId`(二选一)、`session_id`（有则写会话缓存+后台桥接图谱）、`node_set`（List[str]，per-agent/per-project 标签）、`run_in_background`(false)、`custom_prompt`、`chunk_size`(**4096** token)、`chunks_per_batch`(**36**)、`ontology_key`、`graph_model`(JSON schema)、`content_type`('skills'/'cogx-archive')、`import_mode`、`skills_text`/`skill_name` | `get_remember_router.py:104-395` |
| `POST /api/v1/remember/entry` | JSON（判别联合体） | `entry`(type ∈ `qa`/`trace`/`feedback`/`skill_run`)、`dataset_name`(默认 main_dataset)、`session_id`（qa/trace/feedback 必填）、`skill_improvement` | `get_remember_router.py:397-468` |
| `POST /api/v1/recall` | JSON | `query`、`search_type`(默认 GRAPH_COMPLETION；传 `null` 走 auto-route 规则路由)、`datasets`/`dataset_ids`(省略=搜所有有读权限的数据集)、`system_prompt`、`node_name`(按 NodeSet 过滤)、`top_k`(**15**)、`only_context`(false)、`verbose`、`include_references`、`session_id`、`scope`('graph'/'session'/'trace'/'session_context'/'all'/'auto'/列表)、`context_profile`('qa'/'agent') | `get_recall_router.py:26-97,128-225`；scope 规范化 `entries.py:138-188` |
| `GET /api/v1/recall` | — | 返回当前用户的检索历史 | `get_recall_router.py:108-127` |
| `POST /api/v1/improve` | JSON | `extraction_tasks`、`enrichment_tasks`、`data`、`dataset_name`/`dataset_id`(必选一)、`node_name`、`run_in_background`(false)、`build_global_context_index`(false)、`session_ids`(设置后跑完整会话桥接管线) | `get_improve_router.py:21-104`；语义见 `improve.py:35-101` |
| `POST /api/v1/forget` | JSON | `data_id`、`dataset`/`dataset_id`、`everything`(危险全删)、`memory_only`(只清图谱+向量，保留原文件) | `get_forget_router.py:16-126` |

### 1.2 会话/数据集/代理管理

| 方法/路径 | 说明 | 来源 |
|---|---|---|
| `GET /api/v1/sessions` | 分页列表，参数 `range`(24h/7d/30d/all)、`status`、`limit`(**1-500**，默认50)、`offset`、`order_by`(last_activity_at/cost_usd/tokens_in/...)；响应 `{sessions,total,limit,offset,has_more}` | `get_sessions_router.py:83-165` |
| `GET /api/v1/sessions/stats` | 聚合统计（会话数、花费 USD、tokens_in/out、时长、成功率、状态桶） | `get_sessions_router.py:167-273` |
| `GET /api/v1/sessions/cost-by-model` | 按模型分组的 token/成本 | `get_sessions_router.py:275-339` |
| `GET /api/v1/sessions/{session_id}` | 单会话详情（Q&A+轨迹尾部各20条）；404 无权限/不存在 | `get_sessions_router.py:341-405` |
| `GET/POST/DELETE /api/v1/datasets` | 列表（仅用户有 read 权限的）/创建（同名返回已有）/删除全部 | `get_datasets_router.py:93-198` |
| `DELETE /api/v1/datasets/{dataset_id}`、`DELETE /api/v1/datasets/{dataset_id}/data/{data_id}` | 删数据集/删单条数据 | `get_datasets_router.py:200-287` |
| `GET /api/v1/datasets/{id}/graph` | 图谱可视化（节点带 `properties: dict`） | `get_datasets_router.py:289-319` |
| `GET /api/v1/datasets/{id}/data`、`GET /api/v1/datasets/{id}/data/{data_id}/raw` | 数据项列表/原文件下载 | `get_datasets_router.py:321-593` |
| `GET /api/v1/datasets/status` | 管线状态（add_pipeline/cognify_pipeline，pending/running/completed/failed） | `get_datasets_router.py:394-478` |
| `GET/PUT /api/v1/datasets/{id}/schema` | 数据集级 graph schema + custom_prompt 存取 | `get_datasets_router.py:595-649` |
| `POST /api/v1/auth/login`、`/logout`、`/me`；`/auth/register`、`/auth/api-keys` 等 | 登录（OAuth2 表单→Bearer+cookie）、退出、当前用户；注册与 API key 管理 | `get_auth_router.py:14-54`；`client.py:203-223` |
| `POST /api/v1/agents/create?name=`、`GET /agents/list`、`GET/DELETE /agents/{id}` | 创建代理身份（返回一次性 `agentApiKey`，代理=调用者的子用户）；`POST /agents/register`、`/unregister`、`GET /agents/connections...` | `get_agents_router.py:56-150` |
| `POST /api/v1/permissions/tenants`、`/roles`、`/users/{id}/tenants`、`/datasets/{principal_id}` | 租户/角色/ACL 授权（read/write/share/delete） | `client.py:233-237`；官方 API 参考 |
| `/health`、`/api/v1/activity/*`、`/api/v1/llm/*`、`/api/v1/skills`、`/api/v1/search`、`/api/v1/add`、`/api/v1/cognify`、`/api/v1/memify`、`/api/v1/delete`、`/api/v1/update`、`/api/v1/sync`、`/api/v1/export`、`/api/v1/ontologies`、`/api/v1/settings`、`/api/v1/schema`、`/api/v1/visualize`、`/api/v1/responses`、`/api/v1/users`、`/api/v1/checks`、`/api/v1/proposals` | 其余注册端点 | `client.py:203-311` |

### 1.3 已知限制
- recall `top_k` 默认 15（`get_recall_router.py:65`）；sessions `limit` 上限 500（`get_sessions_router.py:103`）；会话详情只回尾部 20 条 Q&A/轨迹（`get_sessions_router.py:403-404`）。
- `/remember` 与 `/add` 只接受 multipart 文件上传；裸文本需走 Python SDK 或先写文件（官方部署指南 "Uploading files, raw text..." 一节，https://docs.cognee.ai/guides/deploy-rest-api-server.md）。
- 错误码惯例：400 参数错、402 token 预算耗尽（`LLMPaymentRequiredError`，`get_remember_router.py:379-383`）、409 处理失败、422 校验错、403 权限不足返回空列表（`get_recall_router.py:215-216`）。

---

## 2. 多主体（多代理）记忆隔离机制

### 2.1 隔离的四个层次（官方文档 + 源码双重确认）

1. **数据集（Dataset）——物理隔离，多用户模式的数据库边界**
   - `ENABLE_BACKEND_ACCESS_CONTROL=true` 时，每个数据集路由到独立的图/向量存储（Dataset Database Handlers），"数据库边界是数据集，而非租户"；租户只是共享权限的用户组（https://docs.cognee.ai/core-concepts/multi-user-mode/multi-user-mode-overview.md）。
   - recall 严格限定在认证用户有 read 权限的数据集内（同一页面 "Isolated Recall"；`recall.py:558-568` 解析 `datasets`/`dataset_ids` 时用 `get_authorized_existing_datasets(..., "read", user)`）。
   - 本地实例实证：`.cognee_system/databases/` 下按数据集 UUID 分目录（`f329fb80-…/` 内是 `main_dataset` 的 LanceDB 表）；`cognee_db` SQLite 的 `datasets` 表为 `(id, name, created_at, updated_at, owner_id, tenant_id)`，本地有 `main_dataset`、`opencode-global`、`opencode-<会话哈希>` 等多个数据集。
2. **会话（Session）——短期记忆隔离，按 `(user_id, session_id)` 双主键**
   - 会话缓存条目按 `(user_id, session_id)` 存储，`session_records` 表 PK 为 `(session_id, user_id)`——两个用户用同一个 session_id 是两个独立会话（https://docs.cognee.ai/core-concepts/sessions-and-caching.md "What Is a Session"；`recall.py:77-97`）。
   - 会话可通过 `dataset_id` 归属到某个数据集（`remember.py:310-334` 写入前 upsert 会话记录并回填 dataset_id）。
   - 可见性规则：用户可见自己的会话 + 子代理的会话 + 通过数据集读权限可见的会话（`get_sessions_router.py:61-77,353-360`；官方 sessions 文档）。
3. **NodeSet——数据集内部的逻辑分组**
   - `remember(..., node_set=["projectA","finance"])` 把标签写进图谱，成为 NodeSet 节点，以 `belongs_to_set` 边连接文档/块/实体；recall 用 `node_name` + `node_name_filter_operator`(OR/AND) 过滤（https://docs.cognee.ai/core-concepts/further-concepts/node-sets.md；`get_remember_router.py:132-141` 参数注释直称 "per-agent or per-project groups"）。
   - 官方明言：NodeSet 让你"保留共享数据集的同时按主题/团队/工作流切片查询"。
4. **用户/代理（User/Agent）——认证与 ACL**
   - agents API 创建的子用户持有独立 API key（`get_agents_router.py:70-87`）；`/agents/register` 时可声明 `dataset_ids`/`dataset_names`/`memory_mode`（官方部署指南 "Agent Management"）。
   - 权限系统：principals（用户/代理/租户）× datasets × read/write/share/delete；ACL 存储（https://docs.cognee.ai/core-concepts/multi-user-mode/permissions-system/overview）。

### 2.2 多数据集读写能力
- 写入：`remember` 一次一个数据集（`datasetName` 或 `datasetId`，`get_remember_router.py:272-276`）；数据集不存在自动创建（`remember.py:1084-1087`）。
- 查询：`recall` 的 `datasets`/`dataset_ids` 为列表，可跨数据集查询；省略则查所有有读权限的数据集（`get_recall_router.py:37-52`）。
- 隔离保证：单用户模式（`ENABLE_BACKEND_ACCESS_CONTROL=false`）下查询时不区分数据集；多用户模式才做物理隔离（官方多用户模式对比表）。

---

## 3. 记忆条目能否携带自定义元数据（project_id / agent_id / 业务实体引用）

**结论：可以，有 4 条路径，能力从强到弱：**

1. **NodeSet 标签（推荐，HTTP API 原生支持）**
   - `POST /api/v1/remember` 的 `node_set` 参数接受任意字符串列表，官方用途即 "per-agent or per-project groups"（`get_remember_router.py:132-141`）；recall 用 `node_name` 精确过滤（`get_recall_router.py:57-64`）。→ 可把 `agent_id`、`project_id` 作为 NodeSet 标签，实现"记忆 ↔ 业务实体"检索维度的交叉引用。
2. **`DataItem.external_metadata: Optional[dict]`（SDK 层）**
   - `cognee/tasks/ingestion/data_item.py:6-11`：`DataItem(data, label, external_metadata, data_id)`；摄取时合并进数据点：`ext_metadata.update(item_external_metadata)` 并存入 `data_point.external_metadata`（`ingest_data.py:162-188`）。→ 任意键值（如 `{"project_id": "...", "entity_id": "..."}`）可随文档入库。
3. **自定义 graph_model / 节点 properties**
   - `remember`/`cognify` 接受 `graph_model` JSON schema 定义抽取实体/关系的字段（`get_remember_router.py:185-195`）；图节点响应含 `properties: dict`（`get_datasets_router.py:57-62`）。→ 在抽取 prompt 中要求把业务实体 ID 作为实体属性提取。
4. **会话条目的既有字段**
   - `QAEntry`: `question/answer/context/feedback_text/feedback_score/used_graph_element_ids`（`entries.py:25-38`）——`context` 可承载业务引用文本，`used_graph_element_ids` 已存检索所用图元素；`TraceEntry.method_params/method_return_value` 为自由 dict（`entries.py:55-56`）；`SkillRunEntry.tool_trace`、`candidate_skill_ids` 等（`entries.py:83-127`）。无自由 `metadata` 字段，但 JSON 型字段可塞任意元数据。

**注意**：`remember/entry` 的 HTTP JSON 路径只有这 4 种固定 entry 类型，无通用 metadata 字段；自由元数据路径是 node_set / SDK DataItem / graph_model。

---

## 4. Token 成本模型、批量写入与蒸馏（improve）行为

### 4.1 什么消耗 token（按操作分类）

| 操作 | 消耗 | 依据 |
|---|---|---|
| 会话缓存写入 `remember(..., session_id)` | **0**（原文直存，无分块/抽取/嵌入） | 官方 sessions 文档 "Session cache vs Permanent memory" 表；`remember.py:1049-1056` |
| recall 会话关键词匹配 / auto-route 规则路由 | **0**（无 LLM） | `recall.py:158-284`（`_tokenize` 词重叠排序）；`query_router.route_query` 规则路由（`recall.py:545-551`） |
| `AUTO_FEEDBACK`（默认开） | 每轮 **1 次结构化输出调用** | 官方 sessions 文档 "Session-context guidance (AUTO_FEEDBACK)" |
| 永久 remember = add+cognify(+improve) | **按量**：分块→每个 chunk 一次 LLM 实体抽取 + 并行 summarize | `get_remember_router.py:161-169`（"Each chunk is processed by the LLM separately"）；`extract_graph_and_summarize.py:21-34` |
| improve（memify 默认路径，无 session_ids） | 少量：triplet 抽取+**纯 embedding**（无 LLM） | `create_triplet_embeddings.py`（无 LLMGateway 调用） |
| improve 带 `session_ids`（蒸馏桥接） | **较多**：feedback 权重、会话 Q&A 重新 cognify（LLM 抽取）、trace 持久化、session 蒸馏的 curator+writer 两次 LLM 调用 | `improve.py:47-73,160-238`；`distill.py`（curator 每批一次调用、writer 每课一次调用） |
| `build_global_context_index` | LLM 摘要 | `improve.py:264-282` |
| 嵌入 | **本地 Fastembed，0 云端费用** | `.env`：`EMBEDDING_PROVIDER="fastembed"`；README 2.1/7 节 |

### 4.2 批量/并行参数（成本杠杆）
- `chunk_size`：默认 **4096** token/块（HTTP，`get_remember_router.py:161-169`）；SDK 自动计算 `min(embedding_max_tokens, llm_max_completion_tokens // 2)`（`cognify.py:111-113`；`llm/utils.py:17-44`）。
- `chunks_per_batch`：HTTP 默认 **36**（`get_remember_router.py:170-176`）；SDK 默认 **100**（`cognify.py:322-324`，temporal 路径 10，`cognify.py:383-384`）。
- `data_per_batch`：默认 **20**（`cognify.py:57`）。
- `EMBEDDING_BATCH_SIZE`：默认 **36**（`embeddings/config.py:104-107`）。
- improve/memify 批：`triplets_batch_size=100`（`create_triplet_embeddings.py:22`）；蒸馏 `CURATOR_BLOCKS_PER_BATCH=6`、`CURATOR_CONCURRENCY=5`、`WRITER_CONCURRENCY=5`、`MIN_GATE_CONFIDENCE=0.75`（`session_distillation/models.py:19-31`）。
- 成本随内容量线性增长，可用 `custom_prompt` 收窄抽取范围、`chunk_size` 调粗粒度（`get_remember_router.py:161-169` 明示大块=少而粗、小块=细而贵）。

### 4.3 触发策略
- `remember` 无 session_id：同步 add+cognify(+self_improvement 的 improve)，或 `run_in_background=true` 立即返回 `pipeline_run_id`（`remember.py:1096-1143`）。
- `remember` 带 session_id：立即返回 `session_stored`，**默认后台** 起 `improve(dataset, session_ids=[...])` 桥接（`remember.py:1049-1081`）；`self_improvement=false` 则留在缓存等显式 `improve`（官方 remember 文档）。
- `improve(session_ids)` 阶段顺序：①feedback 权重 ②会话 Q&A 持久化（`node_set="user_sessions_from_cache"`）②c 蒸馏 lessons（`session_learnings`）②d truth subspace（可选）③memify 富化（`improve.py:47-73,160-238`）。
- 幂等保护：单会话 improve 有锁，重复触发直接跳过（`improve.py:140-158`）；所有桥接阶段 fail-open 不阻断（`improve.py:320-347`）。
- 本地 opencode 插件实测：会话结束 `session.idle` 一次批量写 QA/trace（零 token）+ 一次 `POST /improve`（后台、耗 token），"只有记忆进图谱才花 token"（`D:\Cognee\README.md` 2.2、3.2、7 节）。

### 4.4 成本计量
- `session_records`/`session_model_usage` 记录每会话每模型的 `tokens_in/tokens_out/cost_usd`，`/api/v1/sessions/stats`、`/cost-by-model` 可查询；LLM 未返回精确用量时用字符估算 `len(text)//4`（官方 sessions 文档 Note）。
- token 预算耗尽时 API 返回 **402 Payment Required**（`get_remember_router.py:379-383`）。

---

## 5. 部署为独立服务的关键配置

### 5.1 本地实例实测配置（`D:\Cognee\.env`）
```
LLM_PROVIDER="custom"  LLM_MODEL="deepseek/deepseek-v4-flash"  LLM_ENDPOINT="https://api.deepseek.com"  LLM_API_KEY=…
EMBEDDING_PROVIDER="fastembed"  EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2"  EMBEDDING_DIMENSIONS="384"
DB_PROVIDER="sqlite"  GRAPH_DATABASE_PROVIDER="kuzu"  VECTOR_DB_PROVIDER="lancedb"
CACHING="true"  CACHE_BACKEND="sqlite"
DATA_ROOT_DIRECTORY / SYSTEM_ROOT_DIRECTORY（本机路径）
REQUIRE_AUTHENTICATION="true"  ENABLE_BACKEND_ACCESS_CONTROL="true"  ALLOW_HTTP_REQUESTS="true"  ALLOW_CYPHER_QUERY="true"  ACCEPT_LOCAL_FILE_PATH="true"
HF_ENDPOINT="https://hf-mirror.com"   # fastembed 模型走 HF 镜像
```
（`D:\Cognee\.env`；备份 `.env.bak-isolation` 是 `REQUIRE_AUTHENTICATION=false + ENABLE_BACKEND_ACCESS_CONTROL=false` 的关闭隔离版本）

### 5.2 离线 embedding
- Fastembed = 本地 CPU ONNX，模型缓存于 `%TEMP%\fastembed_cache\`，无网络、无 API key、免费（README 2.1、7 节）；换供应商需 `EMBEDDING_DIMENSIONS` 显式设置，否则回退 3072 会形状不匹配（`embeddings/config.py:11-16,86-102`）。
- 全离线替代：Ollama 同时做 LLM+embedding（`LLM_PROVIDER="ollama"`, `LLM_API_KEY="ollama"` 占位，官方 https://docs.cognee.ai/guides/local-setup.md）；嵌入 batch 默认 36，Ollama 下建议调小（同页）。

### 5.3 启动与代理
- `uvicorn cognee.api.client:app --host 0.0.0.0 --port 8000`（官方部署指南）；`python cognee/api/client.py --agent-mode` 端口 8011、注册代理后无人连接 60 秒自关（`client.py:350-374`）；`HTTP_API_HOST`/`HTTP_API_PORT` 可覆盖。
- 代理：`start-cognee.bat` 启动前加载 `.env.proxy`（`HTTP_PROXY/HTTPS_PROXY`），仅用于扩展/模型下载，业务流量不经过代理（`D:\Cognee\start-cognee.bat`）。
- CORS：`CORS_ALLOWED_ORIGINS` 逗号分隔白名单，默认只放行 UI_APP_URL（`client.py:110-126`）。

### 5.4 鉴权与多租户
- `REQUIRE_AUTHENTICATION=true` 时：注册 `POST /api/v1/auth/register` → 登录拿 Bearer（`get_auth_router.py:14-39`）；JWT 密钥 `FASTAPI_USERS_JWT_SECRET`（`get_token.py:5`）。SDK 侧 `cognee.serve(url=..., api_key=...)` 或 `COGNEE_SERVICE_URL`/`COGNEE_API_KEY` 环境变量（官方部署指南 "Python SDK Client"）。
- `ENABLE_BACKEND_ACCESS_CONTROL=true` 开启数据集级隔离（见 §2）；迁移自 <0.5.0 的数据需先关掉再重摄取（官方多用户文档 Warning）。
- 数据集管理：`POST /api/v1/datasets` 自动建集并授全权限、同名幂等（`get_datasets_router.py:133-184`）；`GET /api/v1/datasets` 只看有读权限的（`:93-131`）。

---

## 6. 多主体记忆隔离可选方案评估

（假设：N 个代理/主体，要求记忆互不可见、可交叉引用业务实体、可批量蒸馏）

| 方案 | 隔离强度 | 成本 | 交叉引用能力 | 运维复杂度 | 评估 |
|---|---|---|---|---|---|
| **A. 每主体一个 Dataset**（`ENABLE_BACKEND_ACCESS_CONTROL=true`） | **物理隔离**（独立图/向量库），recall 天然限定；只共享经授权（permissions API）的数据集 | 每数据集独立 Kuzu/LanceDB 存储；improve 按数据集跑 | 共享数据放独立 dataset + ACL 授权；跨主体查询用 `datasets` 列表 | 中等：需建集 + 授权；本地已见"每会话一数据集"先例（`opencode-<hash>` 数据集） | **首选**。官方多用户模式的数据库边界即数据集；规模可控时最简单可靠 |
| **B. 每主体一个 Session**（同数据集） | 仅短期记忆隔离（缓存按 `(user_id, session_id)`）；**长期图谱不隔离**（同一数据集共享图谱） | 最低（写缓存零 token）；improve 桥接才花钱 | 会话经 `dataset_id` 挂数据集；但图谱层无主体边界 | 低 | 只适合"会话级临时记忆"；**不能**作为长期记忆隔离手段（图谱共享会串记忆） |
| **C. 共享 Dataset + 每主体一个 NodeSet** | 逻辑隔离：recall 用 `node_name` 过滤（OR/AND）；**非物理隔离**（同库同权限层） | 与单数据集相同；improve 一次跑全库 | NodeSet 本身就是 agent_id/project_id 标签，天然支持实体引用 | 最低（无需建集/授权） | 适合主体多、记忆量大、想共享部分记忆的场景；隔离靠调用方纪律 + 过滤参数，防呆弱于 A |
| **D. 每主体一个 Cognee 用户/代理**（agents API） | 用户级认证隔离 + 数据集权限组合；子用户持独立 API key | 同 A；代理注册/连接额外一条 | 权限矩阵可精确到（主体×数据集×操作） | 最高：用户/租户/角色/ACL 四层 | 适合企业多租户；对内部多代理系统过重 |
| **E. 混合（推荐落地形态）**：每主体 Dataset（长期图谱）+ 主体内 Session（短期）+ NodeSet 承载 `project_id/entity_id` 交叉引用 | 兼备 A 的物理隔离与 C 的引用能力 | A+B 之和，可控 | NodeSet + `DataItem.external_metadata` + `context` 三路引用 | 中 | **本 spec 建议方案**：与本地既有运行模式（每会话数据集 + opencode-global 共享集）兼容 |

**结论**：物理隔离选 A（每主体 Dataset）；短会话记忆用 B；"记忆 ↔ 业务实体交叉引用"用 NodeSet 标签 + `DataItem.external_metadata`（SDK）实现；企业级多租户权限才需要 D。隔离开关 `ENABLE_BACKEND_ACCESS_CONTROL` 与鉴权 `REQUIRE_AUTHENTICATION` 必须同时开启才构成完整隔离。
