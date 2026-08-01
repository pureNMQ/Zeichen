# 10 通知 + 搜索 + 附件

Status: open
Type: task
Blocked by: 07, 08

## Question

实现余项功能(规格书 §7 的尾项):
- 站内通知:轻量(未读数、点击跳转,"我关注实体的变更";无偏好系统);触发源=activity
- 全局搜索:search.query 后端(跨实体关键词+语义混合)+ Web 搜索框/结果页
- 附件:attachment 表 + 本地卷存储(单文件 20MB、项目配额 2GB)、attachment.upload/download MCP 工具、软删跟随父实体
- pytest:通知触发、搜索混合检索、附件配额边界

产出:通知/搜索/附件三模块前后端。
