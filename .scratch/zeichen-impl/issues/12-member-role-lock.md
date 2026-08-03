# 12 成员管理角色列:锁定保护 + 下拉展开位置修复

Status: open
Type: task
Blocked by: 03

## Question

实现成员角色锁定(来自 optimization-backlog,已确认):

- **迁移**:新增 `is_bootstrap` 布尔列(单一标记);现存库最早 created_at 的未删除人类用户标 true,新用户一律 false
- **守卫替换(后端)**:删除"最后一名管理员不可降级/不可移除"守卫;新守卫 = 任何人(含 admin)不能改自己的角色、不能移除自己(conflict);`is_bootstrap` 用户角色/移除双锁定(任何人操作都拒绝);`update_role`/`remove_member` 对齐
- **前端角色列三类态**:本人行禁用、首用户禁用、其余可选
- **下拉展开方向(已合并三个问题,全站统一修复)**:成员管理角色下拉、侧边栏"当前项目"切换器、项目详情"添加成员"人选下拉——同一根因(共享 `SelectContent` 用 item-aligned + 自动翻转,空间不足向上弹)。修复落在共享组件 `frontend/src/components/ui/select.tsx`(position="popper" + side="bottom" + 不翻转),一处修复覆盖全站所有 Select 实例,不做逐实例配置
  - ✅ **已提前执行(2026-08-02,用户验证 10 时反馈"每个下拉框都有问题")**:`SelectContent` 默认改为 `position="popper"` + `side="bottom"`(相对触发器、默认向下,消除 item-aligned 的选中项对齐导致的上弹);仅当触发器贴近视口底边时保留智能上翻(否则选项不可达);前端 53 测试全绿
- 测试:前端三类态 + 后端守卫用例

产出:角色变更安全边界(本人禁止 + bootstrap 锁定),UI 三类态正确呈现。
