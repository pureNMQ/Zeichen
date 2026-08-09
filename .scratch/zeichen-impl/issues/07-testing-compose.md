# 07 测试补全 + 本地 compose 全链路

Status: resolved
Type: task
Blocked by: 02, 03, 04, 05, 06, 08

## Question

收尾:补全测试 + 本地全链路可演示(规格书 §8 的本地形态):
- 后端 pytest 覆盖率补齐(状态机/权限/记忆/附件/搜索边界)
- 前端组件测试补齐(Vitest+RTL 核心交互组件)
- 本地 docker-compose.yml 全链路:nginx(或 dev 形态)/api/mcp/cognee/postgres/前端;`docker compose up` 一键可起
- 端到端演示脚本:人类 Web 登录→建项目→建需求→agent 经 MCP 认领任务→完成任务→需求验收→记忆 recall 演示
- 规格书 §9 待验证事实清单逐项核对并回填 spec.md

产出:本地可跑的完整 v1,按演示脚本可验收。

## Answer

**后端测试补全**(154 → **319 个 pytest,91% 覆盖率**,原 79%):新增 8 个测试文件 + 扩展 5 个既有文件,覆盖状态机/权限/记忆/附件/搜索/文档/代码引用/任务/项目/认证/成员/Agent/通知/分页/安全/worker 全部边界;清理 attachments 与 search 的死代码;`MemoryGrant` 模型补导出。仅 mcp_server 进程内 0%(子进程 e2e 测,设计使然)。

**前端组件测试补全**(88 → **100 个,20 文件全绿**):新增 interactions.test.tsx 覆盖 activity-stream / comment-stream(发表/失败通知/只读)/ status-badge / status-select(含禁用态)。

**本地 compose 全链路**(`docker compose up -d` 一键起,已实测):
- 6 服务:nginx(唯一入口:80)→ web 静态 + /api 反代 api + /mcp 反代 mcp(SSE 关缓冲);api(迁移+uvicorn)/ mcp / worker 三容器共用 Dockerfile.backend,不发布宿主端口(§8.1);cognee + postgres 保留宿主发布兼容 start-all.ps1
- 新增 Dockerfile.backend / Dockerfile.frontend / frontend/nginx.conf / .dockerignore
- 实测踩坑与修复:
  - MCP 经 nginx 报 421:SDK 的 Host 白名单按 `host:port` 匹配,nginx 转发的 Host 无端口 → `proxy_set_header Host $host:$server_port` 修复
  - cognee 1.4.1 sessions **无 DELETE 端点**(405)→ `CogneeClient.delete_session` 对 405 容忍(§9 回填);实测 recall 返回数组、Kuzu json 扩展需从 extension.ladybugdb.com 下载(被墙环境预下载挂载 `/root/.lbdb/extension`,gitignore 的 backend/.lbdb-extension)、fastembed/HF 模型缓存持久化为命名卷
- 演示脚本 `scripts/demo-e2e.py`:11 步全链路(引导→登录→项目→需求→任务→Agent+key→MCP 认领→任务三态流转→需求验收→记忆写入+recall 命中→软删清理),幂等可重复跑,**实测全部通过**

**spec §9 回填**:新增 §9.1 已核验事实清单(MCP SDK/IR 编辑器/cognee 1.4.1 端点行为/模型缓存/扩展下载)。

遗留说明:本机 start-all.ps1 时代的宿主进程(8001/8002/5173)仍在运行,与 compose 栈并存,建议演示前关闭以免干扰。
