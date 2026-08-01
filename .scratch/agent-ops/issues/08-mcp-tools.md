# 08 MCP 工具面清单

Status: resolved
Type: prototype
Blocked by: 01, 03, 06

## Question

定稿 MCP 工具面:agent 通过 MCP 能调用哪些工具、每个工具的参数与语义:
- 按域列出工具草案:需求(建/改/关/评论)、任务(建/改/状态流转/指派/认领/评论)、文档(Wiki 页/字典词条/API 定义 的读写)、记忆(recall/remember/管理)、查询(列表/搜索/引用关系)
- 全量读写对齐:删除类操作的工具形态(硬删 vs 软删/归档)
- 错误语义:权限不足、实体不存在、并发冲突(状态已变)如何返回
- 命名与参数规范(与 03 的 MCP 最佳实践一致)

用 /prototype 做一版粗糙的 MCP 工具面清单(stub 或文档骨架)供人审阅,链接为资产。

## Answer

原型见 prototypes/mcp-tools-v0.md,经逐点审阅锁定:
- 单 server + 点号命名空间:requirements/tasks/docs(wiki|glossary|api)/comment/ref/activity/memory/search/project/agent 共 8 域 ~45 工具
- 无 admin 命名空间:成员与 key 管理只在 Web 端
- memory.forget 保留,agent 仅能遗忘自己的记忆
- memory.improve 手动工具砍掉:自动触发= MCP 会话断开即蒸馏 + 15 分钟空闲超时兜底 + 条目阈值(少于 3 条不蒸馏);蒸馏量受会话攒的条目数约束
- search.query 全局跨域搜索(关键词+语义混合)
- tasks.assign 与 claim 分开;docs.api.references 供 agent 改 schema 前自查
- requirements.delete 需二次确认(返回任务数)
- 错误四件套统一:permission_denied / not_found / conflict / invalid_request
- 列表统一 cursor 不透明游标分页,返回 page {items, next_cursor}
- 删除类工具=软删语义+restore;物理清理不进 MCP
