---
name: zeichen-to-tasks
description: 将已确认的 Zeichen Requirement 拆分为小而可验证的执行任务，并在用户确认后创建关联任务。Use when the user asks to break a confirmed requirement or plan into implementation tasks.
---

# Zeichen To Tasks

把“要交付什么”拆成“可独立执行和验证的工作单元”。不为待确认需求拆任务，不自动指派，不强制编排执行。

## 流程

1. 确认当前项目与 Requirement；多项目未指明时请求选择。
2. 用 `requirements.get` 读取需求及需求说明，用 `tasks.list` 查现有任务；若需求为“待确认”，明确告知不能拆分，等待显式确认。
3. 识别可独立验收的纵向切片，避免按文件机械拆分。每项草案包含：标题、简短纯文本描述、关联需求、验证方式、真实前置条件。
4. 任务模型尚无阻塞字段：把前置条件写入描述或用引用表达；不得自动阻止认领、自动改状态或联动状态。
5. 展示完整拆分草案并等待用户确认。
6. 确认后逐项调用 `tasks.create`，传入 `requirement_id`；新任务默认“待办”，不自动指派。
7. 汇报创建的任务标题和验证顺序，建议下一步 `zeichen-implement`。

## 约束

- 长说明写需求说明 Wiki，执行证据写评论。
- 只使用逻辑工具名，如 `tasks.create`、`tasks.list`、`requirements.get`。
- 工具不可用或无权限时保留草案并报告阻塞，不回退本地 issue。
