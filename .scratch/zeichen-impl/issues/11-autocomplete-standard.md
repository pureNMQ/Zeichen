# 11 表单输入框 autocomplete 规范:杜绝浏览器凭据误判

Status: resolved
Type: task
Blocked by: 03

## Question

实现表单规范与全站排查(来自 optimization-backlog,已确认):

- **新建仓库根 AGENTS.md(开发规范,本票起笔)**:禁裸 Input;所有非密码输入框显式 `autoComplete` 语义值(或 off);密码框保持 `current-password`/`new-password`;此后表单实现与 review 强制执行
- 全站表单排查(不限于需求/任务):登录、首用户引导、设置密码、改密码、新建需求/任务、成员添加、Agent 创建、key 签发备注等所有输入框
- 测试:前端表单回归

产出:浏览器不再把业务输入框误判为凭据字段,规范落地 AGENTS.md。

## 实现报告

- 新增根目录 `AGENTS.md` 表单约定：禁止未声明 `autoComplete` 的输入控件；密码仅使用 `current-password` 或 `new-password`。
- 为任务、需求、评论、项目、成员、Agent、Key 备注和删除确认等业务字段补充 `autoComplete="off"`；Agent Key 回看验证密码使用 `current-password`。
- `Input` 与 `Textarea` 的 TypeScript 属性现在强制要求调用方显式传入 `autoComplete`，并新增全站 JSX 审计回归测试。
- 验证：`npm test`（55 passed）、`npm run build`、`npm run lint`（仅既有 Fast Refresh warnings）均通过。

## Answer

根目录表单规范、全站补齐与回归测试已完成；用户验收通过。
