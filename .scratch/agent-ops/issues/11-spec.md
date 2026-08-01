# 11 规格书成稿

Status: resolved
Type: grilling
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10

## Question

把全部已定决策汇成《设计规格书》(中文,存于 spec.md,产品名:贼船 Zeichen),章节:总体架构、数据模型、MCP 工具面、Web 功能面、记忆接入、权限与安全、部署运维、交接说明。与人逐节确认后定稿——这是地图的终点:所有决策落地为一份可直接开工的文档。

需在成稿中裁决的遗留问题(来自 04 与各 ticket 的注释):
- mcp 独立容器 vs 挂进 api 进程(04 推荐独立容器,端点 /mcp)
- 通知与活动流是否进 v1(地图雾区)
- 文件附件是否进 v1(地图雾区)

## Answer

《设计规格书》定稿:docs/spec.md v1.0(9 章:总体架构/数据模型/需求与任务/MCP 工具面/权限与安全/记忆接入/Web 功能面/部署运维/交接说明),经逐节确认:
- 遗留裁决:mcp 独立容器(端点 /mcp);活动流+轻量站内通知进 v1;附件进 v1(本地卷、单文件 20MB、项目配额 2GB、attachment.upload/download 进 MCP)
- 成稿修正:任务模型补验收中态(与需求同构);登录标识由邮箱改为账号(username)
- 实现顺序建议:数据模型→API 核心→MCP server→Web→记忆接入→部署
- 实现时需再验证:cognee update 端点对会话缓存条目的覆盖、MCP SDK TokenVerifier 用法、IR 编辑器选型
