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

## Not yet specified

<!-- 在范围内但还不能精确表述的雾;前沿推进后逐步毕业成 ticket -->

- **需求→任务的追溯链**:需求如何派生任务、任务如何回溯需求,粒度到什么程度——等数据模型总图与需求生命周期定后才有形
- **Wiki/字典/API 模块的编辑与浏览交互细节**:版本历史、引用自动更新(改字段名后 API 文档自动同步?)——等文档模块形态 ticket
- **通知与活动流**:变更通知(人类收到"你的任务被 agent 更新了")、活动日志的形态,是否进 v1——尚不清楚是否值得一个 ticket
- **文件附件**:需求/任务/文档挂附件的能力,存储方式(本地卷 vs 对象存储)——等数据模型定后
- **agent 调度与执行**:agent 完成任务时如何"执行"(本工具只管任务与记忆,还是也调度 agent 跑?),边界尚未明确——很可能 out of scope,等任务模型 ticket 时裁决
- **现有 opencode cognee 插件与既有记忆数据的处置**:退役是直接停用还是导入新工具——细节依赖记忆语义 ticket
- **规格书成稿后的交接方式**:spec.md 的存放位置与结构——地图收尾时定

## Out of scope

<!-- 明确排除在目的地之外的工作;只留 gist + 原因,永远不毕业 -->

(暂无)
