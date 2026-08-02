# 贼船 Zeichen — 设计规格书 v1.0

> 人类与 agent 共用的项目协同管理工具。人类经 Web 访问,agent 经标准 MCP 访问;记忆能力由 cognee 提供。
> 本文档是地图(wayfinder)的终点产物:全部决策已在地图的 10 张 ticket 中逐项裁决,此处汇总为可直接开工的规格。

## 1. 总体架构

### 1.1 形态

单机 Docker Compose 部署(一台云服务器),单团队(Team 单例)多项目。

```
┌─ 云服务器 ──────────────────────────────────────────────┐
│  [nginx] 唯一公网入口(TLS)                              │
│    ├──→ [web]    React SPA(静态文件,多阶段构建)          │
│    ├──→ [api]    FastAPI 业务后端(/api/*)                │
│    ├──→ [mcp]    MCP server 独立容器(/mcp,Streamable HTTP)│
│    └──→ [cognee] 记忆服务(REST API)                     │
│  [postgres] 业务数据库(仅 api 内网访问)                  │
│  [volume]   附件存储 + cognee 数据目录                   │
└─────────────────────────────────────────────────────────┘
```

### 1.2 技术栈

| 层 | 选型 |
|---|---|
| Web | React SPA,由 nginx 托管 |
| API | Python FastAPI |
| MCP | Python 官方 SDK(MCP server,独立容器) |
| 业务库 | PostgreSQL |
| 记忆 | cognee(独立服务,HTTP 调用;100% 依赖,不自建记忆存储) |
| LLM | DeepSeek(仅 cognee 蒸馏/抽取用;读写记忆不耗 token 的路径见 §6) |

### 1.3 边界

- **Zeichen 只记录、不调度**:任务执行发生在外部 MCP 客户端(用户自己的 opencode/Claude Desktop 等);Zeichen 不做任务推送、不跑 agent 运行时
- **标准 MCP,任意客户端可连**;现有 opencode cognee 插件退役(处置见 §8.3)

## 2. 数据模型

### 2.1 公共约定

- 所有业务实体:`id(UUID)`、`created_at`、`updated_at`、`created_by`、`project_id`、`deleted_at`(五件套 + UUID)
- **软删为日常**:业务实体一律软删(`deleted_at` 标记),配 restore;**定时物理清理**由运维级任务执行(清理周期见 §8.2;物理清理时,指向实体的引用行与记忆锚点级联清或留墓碑——实现时定,默认留墓碑显示"已删除")
- **记忆数据不参与业务软删**:记忆删除直接透传 cognee(见 §6)

### 2.2 实体清单

| 实体 | 关键字段 | 说明 |
|---|---|---|
| `user` | username, password_hash, is_agent | 人类与 agent 同表,is_agent 区分;username 为登录账号 |
| `api_key` | user_id, token_hash, revoked_at, note | 仅 agent 签发(见 §5.3) |
| `team` | name | 单例根;未来多团队 = 多行 |
| `workspace_member` | user_id, role | role: admin / member |
| `project` | team_id, name | 资源容器 |
| `project_member` | user_id, project_id, role | role: owner / editor / viewer;人+agent 共用 |
| `requirement` | title, description, status | status: 见 §3.1(需求四态) |
| `task` | title, description, status, assignee_id, requirement_id(可空) | status: 见 §3.2(任务五态);派生任务溯源,独立任务允许 |
| `document` | title, doc_type(wiki/glossary/api), content, metadata JSON | 三子模块一表,差异进 metadata |
| `document_version` | document_id, content, version_no | 全文版本链 |
| `attachment` | target_type, target_id, file_name, size, storage_path | 挂任意实体 |
| `comment` | target_type, target_id, author_id, body | 多态,check 约束 |
| `activity` | target_type, target_id, actor_id, action, summary | 多态;actor 区分 human/agent |
| `reference` | from_type, from_id, to_type, to_id, type | type: derives/documents/implements/mentions |
| `memory_grant` | grantor_id, viewer_agent_id, target_agent_id | 记忆互通授权(只读) |

### 2.3 追溯链

- 任务 → 需求:`task.requirement_id`(可空外键)
- 任意实体互引:`reference` 表,type 有限枚举(derives/documents/implements/mentions);双向可查
- 记忆锚点:记忆条目经 cognee `external_metadata`/`node_set` 携带 `project_id`/`entity_id`,回指业务实体

## 3. 需求与任务

### 3.1 需求状态机

`待办(backlog) → 实现中(in_progress) → 已完成(done)`,侧路 `已取消(cancelled)`

- 无评审态;需求 = 单项目内的验收单元,不支持父子层级,拆解靠任务承接
- **完全自由流转**:任意状态互转(含直达终态),**无任何前置校验**(带未决任务也可直达已完成);唯一约束是同态再转返回 `conflict`
- **状态全手动**:任务状态变化**不影响**需求状态(自动流转已删除),需求状态仅由操作者显式改状态控制
- **验收语义**:置"已完成"由任意有编辑权主体(人/agent)经通用改状态操作完成,无校验、不强制留验收说明;activity 只记状态变更(action=`status`,摘要=旧态→新态),说明/理由经评论留存

### 3.2 任务模型

`待办 → 实现中 → 验收中 → 已完成`,侧路 `已取消`(任务五态;验收中为无仪式感的普通状态)

- `assignee_id` 可空;未指派 = 待认领,任何有编辑权者可认领(claim)
- 已指派任务:仅被指派者本人或团队管理员或项目 owner 可改状态/改派
- **完全自由流转**:任意状态互转(含拖到已完成直达),无前置校验,与需求一致
- 任务状态变化不影响需求状态;需求状态完全由操作者显式控制(见 §3.1)

### 3.3 评论与活动

- 评论即讨论,无"解决/未解决"标记
- 活动:所有变更记入 activity,actor 区分人类/agent(见 §5.3 的凭据设计)

## 4. MCP 工具面

### 4.1 规范

- 单 server + 点号命名空间;工具名小写、`[a-z0-9_.-]`
- 认证:Bearer API key(§5.3);传输:Streamable HTTP,端点 `/mcp`
- 错误四件套:`permission_denied` / `not_found` / `conflict` / `invalid_request`
- 列表统一 cursor 不透明游标分页,返回 `{items, next_cursor}`
- 删除类工具 = 软删语义 + restore;物理清理不进 MCP

### 4.2 命名空间(8 域,~45 工具)

| 命名空间 | 工具(要点) |
|---|---|
| `requirements.*` | create/get/list/update/set_status(任意目标态自由流转,无前置校验)/cancel(set_status("cancelled") 便捷封装)/delete/restore;delete 带任务数二次确认 |
| `tasks.*` | create/get/list/update/set_status(任意目标态自由流转,无前置校验)/assign/claim/unassign/cancel(set_status("cancelled") 便捷封装)/delete/restore |
| `docs.wiki.*` | create/get/list/update/versions/rollback/delete/restore |
| `docs.glossary.*` | create/get/list/update/delete/restore;get 支持按词名 |
| `docs.api.*` | create/get/list/update/references(反向引用自查)/delete/restore;schema 保存校验 |
| `comment.*` | create/list/delete(自己的或 owner/admin) |
| `ref.*` | create/list(双向)/delete |
| `activity.*` | list |
| `memory.*` | recall / remember / forget(仅自己的)/ list |
| `search.*` | query(全局跨域,关键词+语义混合) |
| `project.*` | list / get |
| `agent.*` | whoami |
| `attachment.*` | upload / download(遗留问题 3 新增) |

- 无 `admin.*`:成员与 key 管理只在 Web 端
- 蒸馏工具(improve)不进 MCP:自动触发 + Web 端手动入口

## 5. 权限与安全

### 5.1 角色

| 级别 | 角色 | 权限 |
|---|---|---|
| 工作区 | admin | 成员/agent/key 管理、建项目、自动拥有所有项目 owner 级访问 |
| 工作区 | member | 仅可见已加入项目 |
| 项目 | owner | 项目一切操作 + 成员管理 + 删项目 |
| 项目 | editor | 读写项目内资源,认领/改状态 |
| 项目 | viewer | 只读 |

- **判权只看角色,不看主体类型**:admin 角色的 agent 与人类同权;止损靠吊销 key
- 已指派任务:非本人/管理员的 editor 不能改状态(所有权规则)
- 评论删除:editor 仅自己的,owner/admin 任意

### 5.2 操作矩阵

(见 ticket 06 的完整矩阵;资源 × 动作 × 角色,owner/editor/viewer 三档)

### 5.3 凭据

- 人类:账号 + 密码,自建会话(JWT/Cookie);首用户引导注册为 admin;成员直接添加(账号+角色),首登设密码;无 SMTP
- Agent:API key 仅 agent 签发;**多 key 并存、独立吊销**;明文哈希存储但可回看(管理员输入自己密码验证);删除 agent = 软删 + 全吊销 + 清授权
- 人类不签发 key(保证 activity 中 actor 身份可分)

## 6. 记忆接入(cognee)

### 6.1 架构

记忆能力 100% 依赖 cognee;Zeichen 的记忆层是 cognee REST API 的**薄转接层**。cognee 原生 MVP 接口逐一转接:remember / recall / improve / forget / update / datasets / sessions 等。

### 6.2 写入管线(三层)

| 层 | 内容 | 时机 | token |
|---|---|---|---|
| activity(业务库) | 所有业务变更轨迹 | 即时 | 0 |
| 会话缓存(cognee 短期) | agent 问答/轨迹 + 业务变更一句摘要 | 会话进行中 | 0 |
| 知识图谱(cognee 长期) | 蒸馏产物 + 显式长记忆 | 会话断开/空闲超时 | 耗 |

- 蒸馏自动触发:MCP 会话断开即蒸馏;15 分钟空闲超时兜底;**条目阈值:少于 3 条不蒸馏**
- Web 端保留手动"立即蒸馏"入口

### 6.3 空间与隔离

- **每 agent 一个 cognee Dataset**(物理隔离)+ NodeSet 承载 `project_id`
- 项目记忆 = 跨 Dataset 聚合视图(按 project_id 过滤合并)
- 人类(editor+)可见项目全部记忆;agent 默认仅自己的 + 项目记忆
- **记忆互通(可选)**:admin 授权 agent A 只读 agent B 的 Dataset(ACL read),记入 `memory_grant` + activity;只读不写

### 6.4 遗忘与修正

- 遗忘三层:单条(透传 cognee)/ 按实体(NodeSet/锚点)/ 全清(仅人类 Web 端,二次确认);遗忘记 activity
- 修正 = cognee 原生 `PATCH /api/v1/update`(删旧 + 重摄 + 重蒸馏,data_id 不变、锚点不断);修正记 activity

### 6.5 成本

- 不设硬性预算上限(无自动暂停)
- 可见性:记忆管理页展示每 agent token 消耗(近 7 天/30 天/累计,对接 cognee usage)
- 阈值护栏(§6.2)+ 人类监控

## 7. Web 功能面

### 7.1 信息架构

两级导航:工作区级(项目列表/成员管理/agent 管理/搜索/用户菜单)+ 项目级(需求/任务/文档[Wiki|字典|API]/记忆/设置)。~20 页全进 v1。

### 7.2 关键页面

- **需求**:列表默认,可切换;详情含关联任务、引用面板、评论流、活动流、改状态操作
- **任务**:看板默认,可切换;自由拖拽改状态(拖到已完成直达),认领/删除按权限
- **文档**:Wiki 阅读/编辑/版本历史;字典列表/词条;API 渲染页 + 编辑
- **记忆管理页**(项目级,editor+,viewer 无入口):按 agent 过滤、条目列表(锚点跳转)、详情、删除/清空(二次确认)、修正(cognee update)、token 概览、记忆互通授权配置
- **通知**:轻量站内通知(未读数、点击跳转,"我关注实体的变更";无偏好系统、无邮件/推送)
- **全局搜索**:v1 进,工作区级常驻,与 MCP search.query 同一后端

### 7.3 编辑器

- 内容形态 = Markdown 文本(agent 原生输出,无转换层)
- Web 编辑器采用**即时渲染(IR)模式**(所见即所得),不做双栏、不做富文本

## 8. 部署运维

### 8.1 服务布局

(§1.1)nginx 唯一公网入口;postgres/cognee/api 不发布宿主端口;mcp 独立容器(端点 /mcp,TRANSPORT_MODE=http);cognee 镜像:官方 `cognee/cognee`(API)与 `cognee/cognee-mcp`(若复用官方 mcp,实现时确认;默认自建 mcp 容器)

### 8.2 运维

- 持久化:cognee 数据在 `DATA_ROOT_DIRECTORY` / `SYSTEM_ROOT_DIRECTORY` 两目录,必须挂命名卷;postgres 卷;附件卷
- 备份:`pg_dump` 每日逻辑备份;cognee 文件数据停服 tar/rsync;`.env` 单独归档 + 异地拷贝 + 每月恢复演练
- 安全:`ENABLE_BACKEND_ACCESS_CONTROL=True`(cognee 默认);`FASTAPI_USERS_JWT_SECRET` 必须改;`.env` 用 `${VAR:?}` 守卫
- 升级/回滚:固定镜像 tag,`docker compose pull && up -d`;cognee Alembic 迁移由 api 侧跑
- 物理清理:软删实体的定时清理任务(周期实现时定,默认 90 天),附件配额单项目 2GB、单文件 20MB

### 8.3 迁移

- 现有 opencode cognee 插件退役(处置见 ticket 10 的输入:插件退役后,其既有记忆数据是否导入新工具——**默认不导入**,旧数据留在原 dataset,新工具从零开始;如需迁移,实现时单独评估)

## 9. 交接说明

- 本文档是实现的唯一依据;实现 effort 应新开地图/ticket,按 §1~§8 逐模块落地
- 实现顺序建议:数据模型(§2)→ API 核心(§3,5)→ MCP server(§4)→ Web(§7)→ 记忆接入(§6)→ 部署(§8)
- 实现时需再验证的事实:cognee 各端点在本版本的确切行为(尤其 update 对会话缓存条目的覆盖范围)、MCP SDK 的 TokenVerifier 用法、IR 编辑器的选型(Milkdown/Bisheng 等)
