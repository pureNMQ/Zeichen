# 05 记忆闭环(cognee 转接 + MCP + 记忆管理页)

Status: open
Type: task
Blocked by: 03, 08

## Question

实现记忆层完整闭环(规格书 §6,固定 cognee 1.4.1 的转接验证):
- cognee 薄转接层:remember/recall/improve/forget/update/datasets/sessions 逐一映射;采用 cognee `improve(session_ids)` 的原生会话水位线与并发策略
- 每项目一 Dataset,项目成员共享;Zeichen 后端使用 cognee 服务身份并按项目角色强制访问。废弃 `memory_grant`、agent 间 ACL 与互通授权
- MCP:memory.recall/remember/improve/forget/update/list;remember 必传业务 session_id,后台按项目+agent 命名空间化。无会话关闭工具、无断开/空闲/阈值自动触发
- 所有条目显示创建来源;共享项目中 editor/owner 的 agent 与人类均可删除、修正任意来源条目。修正保持 cognee 删除后重建语义,新 data_id 与新来源,不支持记忆间引用
- 业务变更不进入记忆;记忆仅可用锚点回指业务实体。所有记忆操作写 activity,activity 不反写记忆
- Web:项目级记忆管理(editor+):按来源过滤/条目与锚点跳转/删除/清空(仅人类二次确认)/修正/手动 improve(必须选目标 agent 会话);不做 token 概览
- 项目删除永久清理其 Dataset 与会话缓存
- 验证:固定版本的 cognee Dataset 删除不会自动清理会话缓存时,用于项目删除的定向会话缓存清理接口或替代方案
- 测试:后端转接层映射、项目角色隔离、共享来源、会话命名空间与 improve 增量、替换式更新/遗忘范围/项目删除清理;前端记忆页渲染与手动目标选择

产出:记忆全链路闭环(agent 写入→蒸馏→人类管理)。
