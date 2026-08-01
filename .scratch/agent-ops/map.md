# 地图:Agent-Ops 项目协同管理工具

## Destination

走完这张地图的产出:**一份《设计规格书》**——"人类 + agent 公用的项目协同管理工具"的完整设计,可直接交给实现会话开工。规格书覆盖:总体架构(单机 Docker Compose)、数据模型、MCP 工具面、Web 功能面、cognee 长记忆接入。地图只产出决策,不产出代码;实现是地图完成后的下一个 effort。

## Notes

- 域:项目协同管理(需求 / 任务 / 文档 / 记忆),中文交流,规格书以中文成稿
- 技能:grilling 与 domain-modeling 常备;prototype 用于 MCP 工具面与 Web 功能面;research 用于 cognee 与 MCP 生态事实
- 已锁决策(来自 charting 会话,详见各 ticket):目的地=规格书;独立新仓库+本地 markdown tracker;自建核心数据模型含文档子模块;云端部署;多用户团队模式,agent 也是用户;记忆一等公民双向(agent 经 MCP 读写、人类经 Web 管理);Python(FastAPI)+ React + PostgreSQL + FastMCP;agent=独立 principal,API key 认证,归属团队;单团队(Team 单例)→ Project → 资源;cognee 独立服务走 HTTP;MCP 全量读写对齐+记忆工具,权限兜底;邮箱密码自建会话,首用户管理员;标准 MCP 任意客户端可连,现有 opencode cognee 插件退役
- 团队/项目/资源、用户/agent 的域词汇在 CONTEXT.md 维护
- **产品名:贼船 Zeichen**(charting 会话定;德语"记号/印记",谐音"贼船";spec 与仓库名沿用)

## Decisions so far

<!-- 每个已解决 ticket 一行:标题链接 + 一句话要点 -->

- [02 cognee 能力与多主体记忆隔离](issues/02-cognee-capabilities.md) — cognee 支持四层隔离(Dataset/Session/NodeSet/ACL),推荐每主体一 Dataset + NodeSet 承载 project_id/entity_id;自定义元数据可行(external_metadata/node_set);零 LLM 通道与 token 消耗点已摸清
- [03 MCP 标准与认证方式](issues/03-mcp-standards.md) — 协议 Modern 时代(无握手);自建 Bearer API key 合规可行,TokenVerifier 即可;推荐单 server + 点号命名空间;远程用 Streamable HTTP
- [04 部署与运维方案](issues/04-deployment.md) — 单机 Compose 骨架:反向代理唯一公网入口,mcp 独立容器(端点 /mcp),cognee 数据卷必挂,pg_dump 每日备份;mcp 容器形态留待 11 裁定
- [01 数据模型总图:实体与关系](issues/01-data-model.md) — user/agent 同表(is_agent)+api_key;team 单例→project→资源;workspace_member+project_member 授权,资源级授权 out of scope;task.requirement_id 可空 + reference 表(derives/documents/implements/mentions);comment/activity 多态单表;document 单实体+doc_type;软删+定时物理清理;UUID+五件套公共字段;记忆归 cognee Dataset 经引用回指
- [05 需求生命周期与任务模型](issues/05-requirement-task-model.md) — 需求=单项目验收单元,无层级;状态机 待办→实现中→验收中→已完成+取消,任务驱动自动流转(首任务开工→实现中,全完成→验收中),任何编辑权主体可验收;任务同构 待办→实现中→已完成+取消,assignee 可空,已指派仅本人/管理员可改;评论即讨论;Zeichen 只记录不调度,执行在外部客户端
- [06 权限与角色模型](issues/06-permissions.md) — 两级角色 admin/member × owner/editor/viewer,admin 自动全项目 owner;agent 授权=project_member 同表,默认 editor;API key 仅 agent 签发、多 key 并存独立吊销、明文可回看(管理员密码验证);判权只看角色不看主体类型;操作矩阵 + 所有权规则(已指派任务仅本人/管理员,评论删除 editor 限自己的)
- [07 Wiki/字典/API 文档模块形态](issues/07-doc-modules.md) — Wiki 自由页+可空 parent_id+互引;版本链(保存即版本,回滚=新版本);词条项目级、document 表+别名 metadata;API 定义=OpenAPI 子集 schema+校验+渲染;引用感知警示不自动同步;内容=Markdown 文本,Web 编辑器 IR 模式(无转换层)
- [08 MCP 工具面清单](issues/08-mcp-tools.md) — 原型 mcp-tools-v0.md 锁定:8 域 ~45 工具、单 server 点号命名空间;无 admin 域(key 管理仅 Web);memory.forget 仅限自己的记忆;蒸馏自动触发(会话断开+空闲超时+条目阈值);search.query 全局混合检索;错误四件套 + cursor 分页 + 软删语义统一
- [09 Web 功能面与页面清单](issues/09-web-surface.md) — 原型 web-surface-v0.md 锁定:两级导航 ~20 页全进 v1;记忆管理页=项目级 editor+;全局搜索 v1;需求=列表/任务=看板(可切换);成员直接添加;记忆修正=cognee update 转接
- [10 记忆语义](issues/10-memory-semantics.md) — 三层写入管线(activity→会话缓存→图谱);每 agent 一个 Dataset+NodeSet 承载项目,项目记忆=聚合视图;人类 editor+ 看全,agent 默认自己的+项目,可选只读互通(ACL);三层遗忘;不设预算上限,消耗可见+手动蒸馏仅 Web
- [11 规格书成稿](issues/11-spec.md) — 规格书 docs/spec.md v1.0 定稿(9 章,逐节确认);遗留裁决:mcp 独立容器、站内通知进 v1、附件进 v1;成稿修正:任务补验收中态、账号登录

## Not yet specified

<!-- 在范围内但还不能精确表述的雾;前沿推进后逐步毕业成 ticket -->

- **现有 opencode cognee 插件与既有记忆数据的处置**:退役;既有记忆默认不导入(已载入规格书 §8.3),实现时如需迁移单独评估

## Out of scope

<!-- 明确排除在目的地之外的工作;只留 gist + 原因,永远不毕业 -->

- **agent 调度与执行** — 本工具只记录任务与记忆,不推送任务、不跑 agent 运行时;执行在外部 MCP 客户端发生(05 裁决)。agent 编排平台是另一个产品。
- **通知邮件/推送** — v1 仅站内轻量通知,无偏好系统、无邮件/推送(11 裁决)。
- **记忆自动化预算暂停** — 不设硬性预算上限与自动暂停;消耗可见,决策在人类(10 裁决)。
