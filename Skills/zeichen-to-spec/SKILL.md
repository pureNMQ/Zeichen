---
name: zeichen-to-spec
description: 将已讨论并确认的产品想法整理为可验收的 Zeichen Requirement，并按复杂度创建关联的需求说明 Wiki。Use when the user asks to turn an agreed plan, decision, bug, or research result into a formal requirement.
---

# Zeichen To Spec

把已达成共识的内容转为一条清晰、可独立验收的 Requirement。不要用它替代澄清；信息仍有决定性缺口时先推荐 `zeichen-grill-with-docs`。

## 流程

1. 确认当前项目；
2. 阅读相关 Wiki、词典、需求、任务和研究结论；用 `search.query` 查重，必要时用 `requirements.get` 比较范围和验收标准。
3. 判断是否需要需求说明 Wiki。满足任一条件则建议创建：至少两个任务；涉及权限、数据、接口或兼容性；存在方案取舍；验收或示例较长。
4. 草拟 Requirement 标题和简短纯文本 description。描述只包含用户可观察目标和简要范围，不写 Markdown、清单式验收或实现方案。
5. 草拟需求说明 Wiki（如需要），在其中记录问题、影响、范围、非目标、验收标准、边界、方案和证据来源。
6. 向用户展示全部草案并等待确认。确认后用 `requirements.create` 或 `requirements.update` 写入；新需求默认状态为“待确认”。用 `ref.create` 建立 Requirement 与需求说明 Wiki 的 `documents` 引用。
7. 汇报标题、链接（若宿主提供）和下一步 `zeichen-to-tasks` 建议，不自动拆任务。

## 约束

- 一个独立验收单元一条 Requirement；已有需求完整覆盖时复用，不重复创建。
- 只使用逻辑工具名，如 `requirements.create`、`requirements.get`、`docs.wiki.create`。
- 工具不可用或无权限时保留草案并报告阻塞。
