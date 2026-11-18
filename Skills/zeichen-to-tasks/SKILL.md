---
name: zeichen-to-tasks
description: 将 Zeichen Requirement 拆分为小而可验证的执行任务，并在用户确认后创建关联任务。Use when the user asks to break a confirmed requirement or plan into implementation tasks.
---

# Zeichen To Tasks

把“要交付什么”拆成“可独立执行和验证的工作单元”。允许待确认或实施中的需求按实际工作调整拆分。

## 流程

1. 确认当前项目与 Requirement；多项目未指明时请求选择。
2. 用 `requirements.get` 读取需求及需求说明，用 `tasks.list` 查现有任务。
3. 识别可独立验收的纵向切片，避免按文件机械拆分。每项草案包含：标题、Markdown 正文、关联需求、验证方式、真实前置条件。
4. 任务之间的执行顺序写进正文，可引用相关任务。需求级前置条件使用 `requirements.set_blockers` 记录。
5. 展示完整拆分草案并等待用户确认。
6. 确认后逐项调用 `tasks.create`，传入 `requirement_id`；新任务默认“待办”，不自动指派。
7. 汇报创建的任务标题和验证顺序，建议下一步 `zeichen-implement`。

## 约束

- 长说明可直接写在需求或任务正文，执行证据写关联需求时间轴，并标注来源任务。
- 只使用逻辑工具名，如 `tasks.create`、`tasks.list`、`requirements.get`。
- 工具不可用或无权限时保留草案并报告阻塞，不回退本地 issue。
