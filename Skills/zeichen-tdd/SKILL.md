---
name: zeichen-tdd
description: 以红—绿—重构循环实施 Zeichen 任务，建立最小失败测试、通过实现和安全重构。Use when implementing or fixing code where automated tests or a reproducible check can be added.
---

# Zeichen TDD

这是实施纪律，不是任务记录或验收授权。

## 循环

1. 从任务验收标准提取一个最小可观察行为。
2. 先写一个能稳定失败的最小测试或可重复检查，确认失败原因与目标一致。
3. 写最小实现使其通过；不要提前实现未验收的扩展。
4. 重构模块边界、命名和重复逻辑，保持测试持续通过。
5. 每个垂直切片重复循环，再运行任务范围内的回归检查。

## 例外

若没有可运行测试框架，建立最小可重复的替代验证，并在关联需求的时间轴说明验证限制和结果。

## 边界

只负责验证纪律。用 `timeline.append` 写入关联需求的 `project_id`、`requirement_id`、本次 `request_id`、`source_task`（任务短码）和 `body`（验证命令、结果与限制）。重试同一次写入时复用原请求 UUID。
