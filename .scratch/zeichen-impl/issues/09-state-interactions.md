# 09 状态交互放开:状态机重构(后端+MCP+Web)+ 文档修订

Status: claimed
Type: task
Blocked by: 08

## Question

实现状态交互全面放开(来自 optimization-backlog,用户已确认方案 B 全系决策):

**后端状态机**
- **方案 B 完全自由**:任意状态互转(含已完成直达);需求四态(待办/实现中/已完成/已取消,删验收中);任务五态(待办/实现中/验收中/已完成/已取消,验收中保留为无仪式感的普通状态)
- **删除**:验收说明留存(原 activity/comment 留说明)、需求"无未决任务"校验、需求自动流转(首任务开工/全任务离开未决的自动顶升)
- 权限规则保持:已指派任务仅本人/工作区 admin/项目 owner 可改状态/改派/删除;未指派任意编辑权者;需求任意编辑权

**MCP**
- `requirements.set_status` / `tasks.set_status` 通用工具(参数化任意目标态);`cancel` 保留为 set_status("cancelled") 便捷封装;废除 start/complete 双义工具

**Web**
- 需求看板(四列)/任务看板(五列)自由拖拽改状态,拖到已完成直达无对话框;dnd-kit `DragOverlay` 跟手 + 插入占位高亮
- 任务卡片删除入口(二次确认;后端 delete/restore 已有)

**文档修订(同票完成,Answer 列改动点)**
- docs/spec.md:§3.1/3.2 状态机(需求四态/任务五态、删验收语义/自动流转/校验)、§4.2 工具表(complete→set_status)
- docs/frontend-requirements.md:状态词(需求四态/任务五态)、验收按钮、看板列数、自动流转提示
- CONTEXT.md:验收语义(不再留说明)、需求/任务状态机描述

- 测试:后端状态机全路径(任意互转/四态五态约束/权限)+ MCP set_status 端到端 + 前端看板拖拽/任务删除

产出:Web 拖拽/删除与 MCP set_status 全自由流转闭环,规格文档同步一致。
