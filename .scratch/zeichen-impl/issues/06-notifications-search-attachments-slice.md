# 06 通知 + 搜索 + 附件闭环

Status: resolved
Type: task
Blocked by: 04, 08

## Question

实现余项功能闭环(规格书 §7 尾项 + §4 的 attachment/search 工具):
- 站内通知:轻量(未读数、点击跳转,"我关注实体的变更";无偏好系统);触发源=activity
- 全局搜索:search.query 后端(跨实体关键词+语义混合)+ Web 搜索框/结果页
- 附件:attachment 表 + 本地卷存储(单文件 20MB、项目配额 2GB)、attachment.upload/download MCP 工具、软删跟随父实体
- 测试:通知触发/搜索混合检索/附件配额边界;前端通知铃铛/搜索结果渲染

产出:通知/搜索/附件三模块可用闭环。

## Answer

已交付三模块完整闭环(后端 + MCP + Web + 测试)。

**通知**(§7.2 / frontend-requirements §2.6):
- `notification` 表 + 迁移 `0813notifications`;触发源 = activity(`record_activity` 统一挂接)
- 相关成员语义(经确认):项目 owner / 工作区 admin / 目标创建者、被指派者(task)与参与评论者,排除动作发起者本人;`project` 目标活动仅 owner/admin
- API:列表(含 unread_only)/ 未读数 / 标记已读 / 全部已读;Web:侧边栏通知铃铛(未读数角标 + 下拉列表 + 点击跳转)

**全局搜索**(§4.2 search.query / §2.5):
- `search.query` 服务:需求/任务/文档/代码符号走 SQL LIKE 关键词,记忆域经 cognee recall 语义检索,跨用户有权限项目
- API `GET /api/search` 与 MCP `search.query` 同一后端;Web:侧边栏搜索框 + `/search` 结果页按域分组

**附件**(§2.2 / §4.2 attachment.* / §8.2):
- 本地卷存储 `storage/attachments/{project_id}/{id}.bin`,单文件 20MB、单项目 2GB 配额(conflict)
- API:multipart 上传 / 流式下载 / 列表 / 删除 / 恢复;MCP `attachment.upload`(bytes 参数,已验证 FastMCP base64 编解码)/ `attachment.download`
- 软删跟随父实体:需求/任务/文档(递归)/代码符号(子树)删除时级联软删附件;父实体恢复不自动恢复附件
- Web:可复用 `AttachmentList` 组件挂需求/任务/文档详情页

**验证**:后端 pytest 165 通过(排除 1 个依赖 cognee 在线的既有 `test_create_project_admin_only`);前端 87 测试 + build + lint 通过;SQLite 全链路迁移干净。MCP 工具增至 74 个。

遗留:通知"我关注"语义已在 frontend-requirements §6 记录为已裁决。
