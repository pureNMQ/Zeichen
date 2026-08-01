# 03 需求/任务闭环(后端 API + MCP + Web)

Status: open
Type: task
Blocked by: 02

## Question

实现需求与任务域完整闭环(规格书 §3 + §4 的 requirements/tasks/comment/ref 工具 + §7 页面):
- 后端:requirements/tasks CRUD + 状态机(五态含验收中,自动流转,完成校验无未决任务)、assign/claim/unassign(所有权规则)、验收说明、软删/restore、删除二次确认;comment/activity/ref 多态服务;错误四件套统一
- MCP:requirements.* / tasks.* / comment.* / ref.* / project.* / agent.whoami 工具(~25 个);TokenVerifier 接入 02 的 api_key 服务;cursor 分页;mcp CLI 端到端验证"agent 认领→完成→需求进验收中"
- Web:需求列表(默认列表,可切换)/详情(关联任务/引用/评论/活动/验收)、任务看板(默认看板,dnd-kit 选型在此验)/详情(认领/开始/验收/取消按权限)
- 测试:后端状态机全路径+所有权+并发;前端看板渲染+权限按钮

产出:人类在 Web 管需求任务、agent 经 MCP 干活的完整闭环。
