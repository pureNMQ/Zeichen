# 03 需求/任务 API + 状态机

Status: open
Type: task
Blocked by: 02

## Question

实现需求与任务域(规格书 §3):
- requirements API:CRUD + 状态机(待办→实现中→验收中→已完成+取消)、自动流转(首任务开工→实现中;全任务进验收中→验收中;完成时校验无未决任务)、验收说明、软删/restore、删除二次确认(任务数)
- tasks API:CRUD + 状态机(同构五态含验收中)、assign/claim/unassign(已指派仅本人/管理员)、软删/restore
- comment/activity/ref 多态服务(规格书 §2.3/§3.3):挂任意实体、引用四枚举、activity 记录 actor 区分
- 错误四件套(permission_denied/not_found/conflict/invalid_request)统一中间件
- pytest:状态机全部流转路径 + 所有权规则 + 并发冲突

产出:需求/任务/评论/引用/活动完整后端。
