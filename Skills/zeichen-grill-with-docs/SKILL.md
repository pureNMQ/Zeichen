---
name: zeichen-grill-with-docs
description: 澄清软件需求、产品方案或工作流决策，并将确认后的术语、取舍和需求上下文沉淀到 Zeichen。Use when a request is ambiguous or has unresolved acceptance, permission, data, compatibility, or design decisions.
---

# Zeichen Grill With Docs

逐题采访用户，直到影响交付的决策形成共同理解。

## 流程

1. 必须先明确当前项目，不得猜测。
2. 在代码库或Zeichen中读取已有上下文。
3. 逐题提问，确立采访边界。
4. 制定采访计划。
5. 逐题提问，每次只处理一个决策，问题采用Qn序号。提供多个带序号的选项，被给出建议。收到回答后再提出下一题。
6. 用具体边界场景检验答案，区分目标、非目标、异常和权限边界。
7. 每次决策确认共同理解后，按复杂度沉淀：术语写词典；难逆转且有真实取舍的决定写 ADR Wiki；需求级结论写需求说明或评论。

## 写入规则
- 写入前展示草案并等待用户确认；无确认不发布。
- 工具不可用或无权限时保留草案并报告阻塞。
