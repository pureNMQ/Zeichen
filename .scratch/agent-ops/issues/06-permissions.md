# 06 权限与角色模型

Status: resolved
Type: grilling
Blocked by: 01

## Question

设计授权模型(v1 简单权限):
- 角色集:项目级(管理员/编辑/只读?)与工作区级(管理员/成员?)怎么分层
- agent 授权:agent 的 Project 级授权如何授予/吊销(创建时默认继承什么?)
- API key 生命周期:签发、吊销、轮换;人类在 Web 端管理团队 agent 的操作面
- 敏感操作(删除、权限管理)是否对所有主体一视同仁,还是人类与 agent 有别(MCP 全量对齐下,权限矩阵是否仍有"只有人类能删"的例外)
- 操作矩阵:资源 × 动作 × 角色的最小表格

产出:权限矩阵 + agent 凭据生命周期。

## Answer

- 两级角色:workspace_member(admin/member)+ project_member(owner/editor/viewer);admin 自动拥有所有项目的 owner 级访问
- agent 授权:admin 创建 agent(默认 editor,可调 viewer),授权即 project_member 记录,与人类同表
- API key:仅 agent 可签发(人类只走 Web 会话,保证审计可区分);多 key 并存、独立吊销;明文哈希存储但可回看(管理员输入自己密码验证);删除 agent=软删+全吊销+清授权
- 敏感操作一视同仁:判权只看角色,不看主体类型(is_agent 不参与判权)
- 操作矩阵:owner/editor/viewer 三档 × 资源动作表(见对话);补充所有权规则:已指派任务仅本人/管理员可改状态,评论删除 editor 仅限自己的
