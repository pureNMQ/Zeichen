# 05 记忆闭环(cognee 转接 + MCP + 记忆管理页)

Status: open
Type: task
Blocked by: 03

## Question

实现记忆层完整闭环(规格书 §6,本票验证 §9 的待验证事实):
- cognee 薄转接层:remember/recall/improve/forget/update/datasets/sessions 逐一映射(验证 update 端点对会话缓存条目的覆盖范围)
- 每 agent 一 Dataset + NodeSet 承载 project_id;项目记忆=聚合视图
- 记忆互通:memory_grant 表 + cognee ACL 只读授权;activity 记录
- MCP:memory.* 工具(recall/remember/forget[仅自己的]/list)
- 蒸馏自动触发:会话断开/15 分钟空闲超时/条目阈值(3 条)
- Web:记忆管理页(项目级,editor+):按 agent 过滤/条目列表(锚点跳转)/删除/清空/修正(cognee update)/token 概览/互通授权配置
- 测试:后端转接层映射/锚点回指/遗忘范围;前端记忆页渲染

产出:记忆全链路闭环(agent 写入→蒸馏→人类管理)。
