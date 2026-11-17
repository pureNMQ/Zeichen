---
name: zeichen-deploy-upgrade
description: 按最小范围在生产环境执行 Zeichen 功能升级，保证本次更新功能全部落实，并编写升级部署日志。Use when deploying a completed feature to the production stack, or when an update needs verified rollout on running containers.
---

# Zeichen Deploy Upgrade

在生产环境执行一次功能升级的完整规程：最小范围热更新、数据零意外变更、分层验证、部署日志。本 Skill 面向**实际生产环境**（当前 compose 栈：根 docker-compose.yml + deploy/docker-compose.prod.yml 组合，nginx 唯一入口）。

## v2 净室切换

- 以 [DOC-44](https://zeichen.mochigm.cn/documents/wiki/DOC-44) 查实施状态及演练证据。对最终提交执行 `deploy.ps1 -CheckOnly`，核对其验证回执和 AC-01 至 AC-31。
- 停写窗口先停旧写入和旧清理进程。用 `deploy/prepare_v2_cutover.py` 从一致的旧库和附件快照准备独立新库、新卷和切换清单。旧版原位迁移入口不能发布 v2。
- 按切换清单核对新应用镜像、库和卷，检查 Zeichen 与 MochiSite 后恢复写入，再启用 v2 维护。恢复写入前失败切回旧库、旧卷、旧应用和入口配置；已开放写入后先保全新版增量。

下文仅用于 v1 常规升级。

## 前置检查（每次必做）

1. 确认当前项目与本次升级对应的 Requirement/Task 及其验收范围；读取相关 Wiki 与评论。
2. **确认生效 compose 组合**：以运行中容器的 compose 标签为准（`com.docker.compose.project.config_files`），生产必须为「根 docker-compose.yml + deploy/docker-compose.prod.yml」双文件；不得只带根文件执行 compose 命令。
3. 记录回滚点：本次涉及容器的当前镜像 ID/tag、compose 配置快照、数据库版本（alembic version）、关键数据行数。
4. 展示升级计划：涉及容器清单、命令草案、验证清单、回滚预案，等待用户确认后才执行。

## 最小范围热更新

- **只 build/up 本次更新涉及的容器**；postgres 等与本次无关的容器一律不重建、不重启。
- 命令必须带完整的生效 compose 组合（`-f docker-compose.yml -f deploy/docker-compose.prod.yml`），禁止裸 `docker compose up`。
- 破坏性操作（容器重建、镜像变更、restart）执行前先展示具体命令并等待确认；确认一次执行一次，不批量默认。
- 升级期间禁止直接修改数据库凭据（如 ALTER USER）；凭据问题一律先排查配置与 .env，报告阻塞而不是改库。

## 数据库边界

- 升级过程中对数据库只允许只读验证（SELECT）；**禁止 ALTER / DROP / UPDATE / INSERT**（含密码类操作）。
- 表结构变更仅允许通过随更新发布的 alembic 迁移执行；迁移前确认生产库当前版本与目标版本，执行后记录版本。
- 清理本次移除模块的遗留孤儿空表属于允许项，但必须：先 SELECT 确认行数为 0、展示影响（表名+行数）、写入部署日志。
- 任何数据修改意图（即使看起来无害）先展示 SQL 与影响，等待用户确认。

## 分层验证清单（功能全部落实才算完成）

1. **代码层**：本次更新的后端 pytest、前端 vitest、tsc/build、lint 全绿。
2. **产物层**：线上 bundle 版本指纹与本地一致；扫描产物确认无本次移除内容的残留（如旧模块字符串）。
3. **运行层**：涉及容器 healthy；健康检查 200；登录、API、MCP 连通性逐项验证。
4. **功能点**：对照 Requirement 验收范围逐项核对，每项给出证据；未落实项明确列出并报告。

## 部署日志（必写）

升级完成后在项目 Wiki 创建或追加「部署日志」页面（`docs.wiki.create` / `docs.wiki.update`），每条记录：

- 时间、对应 Requirement/Task 与提交/产物指纹
- 本次更新范围与涉及容器（明确"未动"的容器）
- 数据库变更（迁移版本、孤儿表清理明细；无变更则写明"无"）
- 验证结果（分层清单摘要 + 命令与结论）
- 回滚点与失败预案

日志写入前展示草案并等待用户确认；无确认不发布。

## 失败处理

- 升级失败：按回滚预案恢复（旧镜像/旧配置/迁移回退），保留现场证据，报告原因与影响。
- 工具不可用或无权限：保留草案与证据，明确报告阻塞原因与下一步；不得用聊天摘要冒充已写入日志。
