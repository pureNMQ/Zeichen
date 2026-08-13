---
name: zeichen-implement
description: 按 Zeichen 任务执行软件变更，默认使用本地仓库和可运行测试，并把实施证据写回任务。Use when the user asks to implement, fix, or deliver a specific task.
---

# Zeichen Implement

执行已确认的任务，不负责平台内调度。

## 开始前

1. 确认当前项目和任务权限；
2. 用 `tasks.get`、`requirements.get`、相关 `docs.wiki.*` 和 `comment.list` 读取范围与上下文。
3. 若关联 Requirement 为“待确认”，停止并明确告知用户“该需求尚未确认，无法开始实施”。
4. 检查本地仓库、项目规则和现有测试。若任务描述有前置条件或阻塞，检查并报告风险。
5. 展示目标任务、工作范围、验证计划和潜在风险，等待用户确认后才修改文件。

## 实施与回写

1. 默认进入 `zeichen-tdd`。
2. 运行适用的测试、类型检查、lint、构建或人工验证，并记录命令和结果。
3. 用 `comment.create` 回写：完成范围和验证结果必填；影响项、风险/阻塞/验收注意事项按适用项填写。
4. 当前会话实施或修改过的任务严禁设置为“已完成”。完成后只可调整为“验收中”。
5. 不因任务完成自动完成关联 Requirement。

## 约束

- 不自动创建新需求或任务；发现范围缺口时先报告并推荐对应 Skill。
- 工具不可用或无权限时保留草案/证据并报告阻塞。
