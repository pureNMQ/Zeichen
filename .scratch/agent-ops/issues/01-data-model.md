# 01 数据模型总图:实体与关系

Status: resolved
Type: grilling
Blocked by:

## Question

设计核心数据模型:哪些实体(用户/agent、团队、项目、需求、任务、文档/Wiki、字典词条、API 定义、评论、授权)、它们的字段轮廓、以及彼此的关系(多对多?层级?)——特别要定:
- 需求→任务→文档的可追溯链接如何表达
- 评论/活动挂在哪一层
- 授权(成员-项目、agent-项目)的落点
- 数据模型如何预留"多用户以后不推倒重来"的余地(虽然 v1 单团队)

产出:实体-关系草案,作为后续所有 ticket 的共同底座。用 domain-modeling 维护词汇表(CONTEXT.md)。

## Answer

实体总清单经 grilling 逐项确认(详见对话),要点:
- 人类与 agent 同表 user,is_agent 区分;api_key 可吊销
- team 单例根 → project → 资源;多用户预留天然解决(多行即多团队)
- 授权:workspace_member + project_member(owner/editor/viewer),人+agent 共用,资源级授权 out of scope
- 追溯链:task.requirement_id 可空外键(派生任务溯源,独立任务允许) + 通用 reference 表(from/to + type: derives/documents/implements/mentions,有限枚举)
- 评论与活动:多态单表 comment/activity + target_type check 约束
- 文档:单一 document 实体 + doc_type(wiki/glossary/api),差异靠 content + metadata JSON;膨胀后拆表
- 删除:软删(deleted_at)为日常 + 定时物理清理;物理清理时引用/记忆锚点级联或留墓碑(清理周期归 11)
- 公共字段:UUID + created_at/updated_at/created_by/project_id/deleted_at 五件套
- 记忆空间不进业务库,归 cognee Dataset,经 reference/元数据回指实体
