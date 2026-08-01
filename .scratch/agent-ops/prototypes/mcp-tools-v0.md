# MCP 工具面原型 v0(待审阅)

> 基于 03 研究(单 server + 点号命名空间)、01 数据模型、05 状态机、06 权限、07 文档形态。
> 全部工具经同一鉴权: Bearer API key → 解析 agent 身份 → 角色判权。权限不足一律返回 `permission_denied`。

## 通用错误语义(所有工具)

| 错误 | 含义 | HTTP 类比 |
|---|---|---|
| `permission_denied` | 角色无权(如 viewer 写) | 403 |
| `not_found` | 实体不存在(含已软删且无权查看) | 404 |
| `conflict` | 状态冲突/版本过期(如改已关闭的需求) | 409 |
| `invalid_request` | 参数校验失败(schema 不合法等) | 400 |

## 命名空间总览

```
requirements.*   需求域
tasks.*          任务域
docs.*           文档域(wiki / glossary / api 三子域)
comment.*        评论(多态,任意实体)
ref.*            引用(任意实体互引)
activity.*       活动查询
memory.*         记忆(cognee)
search.*         全局搜索
project.*        项目
agent.*          agent 身份自省
```

## requirements.*(需求)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `requirements.create` | project_id, title, description? | requirement | 状态=待办 |
| `requirements.get` | id | requirement | 含状态、引用数、评论数 |
| `requirements.list` | project_id, status? , cursor? | page | 按项目过滤,可按状态过滤 |
| `requirements.update` | id, title?, description? | requirement | 仅非终态(已完成/已取消不可改) |
| `requirements.complete` | id, note? | requirement | 仅验收中→已完成;note 为验收说明 |
| `requirements.cancel` | id, reason? | requirement | 任意非终态→已取消 |
| `requirements.delete` | id | {deleted: true} | 软删;已有任务的需先确认(返回任务数) |
| `requirements.restore` | id | requirement | 软删恢复 |

> 状态流转的"实现中"不设手动工具——由任务驱动自动。

## tasks.*(任务)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `tasks.create` | project_id, title, requirement_id?, assignee_id?, description? | task | requirement_id 可空(独立任务) |
| `tasks.get` | id | task | |
| `tasks.list` | project_id?, requirement_id?, assignee_id?, status?, cursor? | page | 多维过滤 |
| `tasks.update` | id, title?, description? | task | 仅非终态 |
| `tasks.start` | id | task | 待办→实现中;自动带需求进实现中 |
| `tasks.complete` | id | task | 实现中→已完成;触发需求"全完成→验收中"检查 |
| `tasks.assign` | id, assignee_id | task | 未指派可任意 assign;已指派仅本人/管理员可改派 |
| `tasks.claim` | id | task | 未指派时,把自己设为 assignee |
| `tasks.unassign` | id | task | 本人或管理员 |
| `tasks.cancel` | id, reason? | task | 任意非终态 |
| `tasks.delete` | id | {deleted: true} | 软删 |
| `tasks.restore` | id | task | |

## docs.*(文档域)

### docs.wiki.*(Wiki 页)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `docs.wiki.create` | project_id, title, content, parent_id? | doc | parent_id 可空(自由页) |
| `docs.wiki.get` | id | doc | 含版本号 |
| `docs.wiki.list` | project_id, cursor? | page | |
| `docs.wiki.update` | id, content?, title?, parent_id? | doc | 保存即新版本 |
| `docs.wiki.versions` | id, cursor? | page | 版本链 |
| `docs.wiki.rollback` | id, version | doc | 回滚=复制为新版本 |
| `docs.wiki.delete` | id | {deleted: true} | 软删 |
| `docs.wiki.restore` | id | doc | |

### docs.glossary.*(字典词条)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `docs.glossary.create` | project_id, term, definition, aliases? | doc | |
| `docs.glossary.get` | id 或 term? | doc | 支持按词名查 |
| `docs.glossary.list` | project_id, prefix?, cursor? | page | |
| `docs.glossary.update` | id, term?, definition?, aliases? | doc | 版本链同 wiki |
| `docs.glossary.delete` / `restore` | id | | |

### docs.api.*(API 定义)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `docs.api.create` | project_id, name, description?, schema | doc | schema=OpenAPI 子集,保存时校验 |
| `docs.api.get` | id | doc + 结构化 schema | agent 读到的是 JSON schema |
| `docs.api.list` | project_id, cursor? | page | |
| `docs.api.update` | id, name?, schema?, description? | doc | 保存时校验 + 返回反向引用警示(references: [...]) |
| `docs.api.references` | id, field_path? | list | 谁引用了此 API/字段(引用感知) |
| `docs.api.delete` / `restore` | id | | |

## comment.*(评论,多态)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `comment.create` | target_type(requirement/task/doc), target_id, body | comment | editor+ |
| `comment.list` | target_type, target_id, cursor? | page | viewer+ |
| `comment.delete` | id | {deleted: true} | 自己的 或 owner/admin;软删 |

## ref.*(引用)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `ref.create` | from_type, from_id, to_type, to_id, type(derives/documents/implements/mentions) | ref | editor+;校验目标存在 |
| `ref.list` | to_type?, to_id?, from_type?, from_id?, type?, cursor? | page | 双向查询(反向引用靠这个) |
| `ref.delete` | id | {deleted: true} | editor+ |

## activity.*(活动)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `activity.list` | target_type?, target_id?, actor_type?, cursor? | page | viewer+;actor 区分 human/agent |

## memory.*(记忆,cognee)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `memory.recall` | query, scope(auto/session/graph), top_k? | results | 零 LLM 通道优先(auto-route) |
| `memory.remember` | content, metadata?(project_id/entity_id) | ok | 写入会话缓存(零 token);可选挂实体锚点 |
| `memory.improve` | scope? | job | 蒸馏进知识图谱(耗 token,后台);一般自动触发,工具备用 |
| `memory.forget` | scope, entity_id?, dataset? | ok | 遗忘:清会话/清图谱(按 02 的 dataset 机制) |
| `memory.list` | project_id?, agent_id?, cursor? | page | 人类视角的管理查询(agent 也可用) |

## search.*(全局搜索)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `search.query` | query, project_id?, entity_types?, cursor? | page | 跨需求/任务/文档/词条/API 的全文+语义混合检索 |

## project.*(项目)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `project.list` | | page | 当前主体可见的项目 |
| `project.get` | id | project | |

## agent.*(身份自省)

| 工具 | 参数 | 返回 | 语义 |
|---|---|---|---|
| `agent.whoami` | | {id, name, roles, keys_count} | agent 确认自己的身份与权限 |

## 规格说明(约束)

- 工具名全部小写、点号命名空间,符合 03 的 MCP 规范(1-128 字符,[A-Za-z0-9_.-])
- 输入参数一律结构化对象;分页统一 `cursor`;列表返回统一 `page {items, next_cursor}`
- 删除类工具 = 软删语义,配 restore;真物理清理不进 MCP(运维侧)
- 无 `admin.*` 命名空间——成员/key 管理走 Web 端,不给 agent(admin 角色的 agent 需要时,经 Web 端操作)
