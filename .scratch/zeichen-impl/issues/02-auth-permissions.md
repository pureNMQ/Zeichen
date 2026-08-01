# 02 认证 + 权限服务

Status: open
Type: task
Blocked by: 01

## Question

实现认证与授权(规格书 §5),业务 API 的鉴权地基:
- 账号+密码登录、会话(JWT/Cookie)、首用户引导(创建 admin)、成员直接添加(账号+角色,首登设密码)
- API key 生命周期:仅 agent 签发、多 key 并存独立吊销、哈希存储、回看明文(管理员密码验证)
- 权限判定服务:workspace_member/project_member 两级角色;admin 自动全项目 owner;判权只看角色
- 操作矩阵 + 所有权规则(已指派任务仅本人/管理员)落地为可复用的授权函数
- pytest:认证流程 + 权限矩阵全覆盖

产出:auth 中间件 + 权限服务,后续所有业务票依赖的鉴权底座。
