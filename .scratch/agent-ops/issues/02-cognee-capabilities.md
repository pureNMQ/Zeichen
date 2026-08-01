# 02 cognee 能力与多主体记忆隔离

Status: resolved
Type: research
Blocked by:

## Question

调研 cognee(项目内已有本地安装 D:\Cognee 与 REST server,可查 README、源码、官方文档)并回答:
- REST API 全貌:remember / recall / improve / forget / datasets / sessions 的参数与限制
- 多主体(多 agent)记忆隔离用什么机制:per-agent dataset?per-agent session?cognee 是否支持多 dataset 写入与查询隔离
- 记忆条目能否挂自定义元数据(如 project_id / agent_id / 指向业务实体 id),供规格书设计"记忆↔业务实体互引"
- token 成本模型与批量写入(improve)的行为细节
- cognee 独立服务部署的关键配置(embedding 本地化、代理、数据集管理)

产出:事实清单 + 对"多 agent 记忆隔离"的可选方案评估,写入 research/cognee-capabilities 分支,链接回本 ticket。

## Answer

已由 research 子代理解决,完整事实清单见 research/cognee-capabilities.md(commit afdb644)。

要点:
- REST API 面约 30 个路由组,核心:remember(多部分文件上传,chunk_size 默认 4096、chunks_per_batch 36)、remember/entry(qa/trace/feedback/skill_run)、recall(search_type=null 走零 LLM auto-route,top_k 15)、improve、forget、sessions、datasets、agents、permissions
- 多主体隔离四层:Dataset(多用户模式下物理隔离,数据库边界即数据集)、Session((user_id, session_id) 双主键,仅短期缓存)、NodeSet(数据集内逻辑分组)、用户/agent ACL。推荐:每主体一 Dataset + 主体内 Session + NodeSet 承载 project_id/entity_id
- 自定义元数据可行:node_set 标签(HTTP 原生)、SDK 层 DataItem.external_metadata、graph_model 自定义 schema 与节点 properties;QAEntry 本身无自由 metadata 字段
- token 成本:会话缓存写/recall 关键词检索/本地 Fastembed 嵌入零成本;消耗点是 cognify 每 chunk 一次 LLM 抽取、AUTO_FEEDBACK 每轮结构化输出、improve 会话重抽+蒸馏(预算耗尽 402)
- 部署:.env 已配 DeepSeek 云端 LLM + Fastembed 离线嵌入 + SQLite/Kuzu/LanceDB 全本地存储;REQUIRE_AUTHENTICATION / ENABLE_BACKEND_ACCESS_CONTROL 决定隔离强度
