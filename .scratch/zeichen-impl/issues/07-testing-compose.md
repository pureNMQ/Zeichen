# 07 测试补全 + 本地 compose 全链路

Status: open
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
