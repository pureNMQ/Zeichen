---
name: zeichen-self-check
description: Audit Zeichen during feature development, bug fixes, refactors, reviews, or release preparation; verify defects against repository rules, product specifications, tests, and observable behavior; deduplicate findings and publish confirmed, independently acceptable changes as requirements in the Zeichen project through ZeichenMCP. Use when Codex is developing Zeichen and should perform a self-check, inspect changed or related code for existing defects, run a pre-handoff quality pass, or submit discovered problems as Zeichen requirements.
---

# Zeichen 自检与提需

对正在开发的 Zeichen 做有证据的质量检查。只把已确认且可独立验收的问题发布为 Zeichen 项目中的需求，不把猜测、重复项或纯实现任务冒充需求。

## 工作流

### 1. 确定检查范围

- 读取仓库根部 `AGENTS.md` 与 Zeichen 项目 Wiki 中 DOC-41 的相关章节。
- 检查 `git status` 和相关 diff，将新增或修改代码作为最低检查范围，并检查其直接调用方、被调用方及共享契约。
- 若仓库根存在 `.codegraph/`，按 `AGENTS.md` 先用 CodeGraph 定位和理解代码；不存在时再使用 `rg` 和定向读取。
- 用户要求全量审计时，按功能切片检查；否则不要把局部改动无边界扩展成全仓重审。

### 2. 执行自检

读取 [references/checklist.md](references/checklist.md)，选择与当前变更有关的检查面。至少执行：

1. 静态检查相关实现、测试和契约。
2. 运行能证明或反驳候选问题的最小测试、lint、类型检查或构建命令。
3. 对 UI 行为或集成行为，仅在可安全访问对应环境时做实际复现；明确区分本地代码事实与已部署实例行为。
4. 记录命令、关键输出、文件与行号。输出中隐藏 token、密码、Cookie、连接串和个人数据。

不要为了自检顺手修复缺陷。除非用户同时要求修复，否则本 skill 只检查、验证、查重和提需。

### 3. 建立发布门槛

每个候选问题必须同时具备：

- **违反项**：与规格、仓库规则、公开契约或可合理期待的行为冲突。
- **可复现证据**：稳定步骤、失败测试、错误响应，或能直接证明问题的代码路径。
- **用户影响**：说明谁在什么情况下受到什么影响。
- **预期结果**：描述修复后的可观察行为，不限定不必要的实现方案。
- **验收标准**：至少一条可客观验证，且包含必要的回归保护。
- **边界清晰**：可作为单项目内一个独立验收单元。

以下内容不要发布：未经验证的怀疑、纯风格偏好、没有用户影响的重构建议、测试环境偶发故障、已存在需求的重复副本，以及当前变更已经修复且验证通过的问题。

### 4. 在 Zeichen 中查重

1. 调用 `project.list`，选择名称精确为 `Zeichen` 的项目；若不存在或出现多个同名项目，停止发布并向用户说明。
2. 用 `search.project` 传入 `project_id`、`query` 和 `domains=["requirement"]` 搜索问题的核心行为或错误信息。
3. 用 `requirements.list` 检查该项目的各状态的需求；遵循 cursor 直到无下一页。状态不同不代表不是重复项。
4. 对疑似重复项调用 `requirements.get` 比较范围和验收标准。

若已有需求完整覆盖问题，不新建需求；报告现有需求 ID 和标题。只有新增证据会实质改变该需求的复现、影响或验收方式时，才用 `timeline.append` 在现有需求的时间轴补充证据，传 `project_id`、`requirement_id`、本次 `request_id` 和 `body`。

### 5. 发布需求

通过 `requirements.create` 发布到已确认的 Zeichen `project_id`。每个独立验收单元创建一条需求；不要把无关问题合并，也不要为同一根因的多个表象重复提需。

标题使用 `修复：<用户可观察的问题>`，避免只写文件名、异常名或实现方案。描述使用以下结构：

```markdown
## 问题
<当前错误行为，以及触发条件>

## 影响
<受影响的用户/agent、功能和严重程度>

## 复现与证据
1. <最小复现步骤>
2. <实际结果>

证据：<测试/命令结果，及 repo-relative 文件:行号；不得包含秘密>

## 预期结果
<修复后可观察的产品行为>

## 验收标准
- [ ] <可客观验证的结果>
- [ ] <相关自动化回归测试或人工验证>

## 范围说明
<必要的边界、兼容性或非目标；未知则省略>
```

`requirements.create` 成功后保存返回的需求 ID。不要自动创建任务、指派人员或改变需求状态；这些是后续规划动作。

### 6. 汇报结果

最终按以下三组简要汇报：

- 已发布：需求 ID、标题、关键证据。
- 已去重：现有需求 ID、标题，以及是否补充了时间轴证据。
- 未发布：候选问题和未达到发布门槛的原因。

若没有确认缺陷，明确说明“未发现达到提需门槛的问题”并列出实际执行的验证。若 ZeichenMCP 不可用、没有写权限或发布失败，不得回退到 `.scratch` 或其他本地 issue 文件；保留需求草稿并向用户报告阻塞原因。
