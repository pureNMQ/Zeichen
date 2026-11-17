---
name: zeichen-implement
description: 按 Zeichen 任务执行软件变更，默认使用本地仓库和可运行测试，并把实施证据写回任务。Use when the user asks to implement, fix, or deliver a specific task.
---

# Zeichen Implement

执行已确认的任务，不负责平台内调度。

## 开始前

1. 确认当前项目和任务权限；
2. 按 [Use Zeichen](../use-zeichen/SKILL.md) 确认连接版本；读取任务、关联需求、相关 Wiki 及需求记录。
3. 若关联 Requirement 为“待确认”，停止并明确告知用户“该需求尚未确认，无法开始实施”。
4. 检查本地仓库、项目规则和现有测试。若任务描述有前置条件或阻塞，检查并报告风险。
5. 按用户已确认的范围和验证计划实施。只有范围发生实质变化时才确认新增工作。
6. 列表类上下文读取遵循筛选约定:`tasks.list` / `requirements.list` 默认筛近 3 天活跃项(`updated_within_days=3`),显式传筛选参数(多值状态/时间窗口/关键词,任务可加负责人),列表默认按 `updated_at` 倒序。

## 实施与回写

1. 默认进入 `zeichen-tdd`。
2. 运行适用的测试、类型检查、lint、构建或人工验证，并记录命令和结果。
3. 按 [Use Zeichen](../use-zeichen/SKILL.md) 把完成范围与验证结果写回关联需求，并注明来源任务。影响项、阻塞和验收注意事项按实际情况填写。
4. 完成本会话任务并回写证据后，可直接将任务置“已完成”；但不得将关联 Requirement 置“已完成”（需求完成由验收主体显式执行）。
5. 不因任务完成自动完成关联 Requirement。

## 约束

- 不自动创建新需求或任务；发现范围缺口时先报告并推荐对应 Skill。
- 工具不可用或无权限时保留草案/证据并报告阻塞。
