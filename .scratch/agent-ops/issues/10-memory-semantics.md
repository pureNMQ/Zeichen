# 10 记忆语义:什么进记忆、如何引用、成本控制

Status: claimed
Type: grilling
Blocked by: 01, 02

## Question

定稿记忆的语义模型:
- 什么内容进长期记忆:agent 的对话?决策记录?产物摘要?哪些进会话缓存、哪些进知识图谱(依赖 02 的能力事实)
- 记忆空间划分:每个 agent 一个 dataset/空间,还是按项目分?人类能否跨 agent 检索
- 记忆↔业务实体互引:记忆条目如何链接回需求/任务/文档(依赖 01 与 02 的元数据能力)
- 人类的管理动作:浏览、修正、删除、清理某 agent 的记忆;遗忘的语义
- 成本控制:哪些操作耗 token、如何给人类可见(记忆管理页展示成本)、批量蒸馏(improve)的触发策略
- 现有 opencode cognee 插件与其既有记忆数据的处置(退役即弃 vs 迁移)

## 已锁定的输入(grilling 阶段)

- **记忆能力 100% 依赖 cognee**:Zeichen 的记忆层是 cognee REST API 的**薄转接层**,不自建记忆存储
- **cognee 原生 MVP 接口都要有对应转接**:remember/recall/improve/forget/update/datasets/sessions 等,Zeichen 侧逐一映射(08 的 memory.* 工具面即其镜像)
- **记忆部分的删除不做 Zeichen 软删**:直接透传 cognee(如 forget);业务实体(需求/任务/文档)仍按 01 软删,记忆不参与
- 记忆修正 = cognee 原生 PATCH /api/v1/update(删旧+重摄+重蒸馏,data_id 不变锚点不断)
- 蒸馏自动触发:MCP 会话断开即蒸馏 + 15 分钟空闲超时兜底 + 条目阈值(少于 3 条不蒸馏)

产出:记忆语义规格。
