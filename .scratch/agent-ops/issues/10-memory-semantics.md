# 10 记忆语义:什么进记忆、如何引用、成本控制

Status: resolved
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

## Answer

- 写入管线三层:活动轨迹(业务库 activity,0 token)→ 会话缓存(cognee 短期,0 token,业务变更自动一句摘要进缓存)→ 知识图谱(蒸馏,耗 token);agent 对话默认进缓存,阈值外才蒸馏
- 空间划分:每 agent 一个 cognee Dataset(物理隔离)+ NodeSet 承载 project_id;项目记忆=跨 Dataset 聚合视图
- 权限:人类 editor+ 看项目全部记忆;agent 默认看自己的+项目记忆,可选互通(admin 授权只读其他 agent 的 dataset,ACL read,记 activity);agent 之间默认互不可见
- 遗忘三层:单条(透传 cognee)/ 按实体(NodeSet/锚点过滤)/ 全清(仅人类 Web 端二次确认);遗忘记 activity
- 成本:不设硬性预算上限(无自动暂停);可见性=记忆管理页 token 消耗(7/30 天/累计,对接 cognee usage);手动蒸馏入口仅 Web 端
