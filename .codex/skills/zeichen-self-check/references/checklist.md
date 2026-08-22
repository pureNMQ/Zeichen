# Zeichen 自检清单

只加载并执行与当前范围有关的条目。仓库当下的 `AGENTS.md`、`CONTEXT.md` 和 `docs/` 规格始终优先于本清单。

## 通用正确性

- 用户路径是否可完成，空态、加载态、错误态和重试是否一致。
- 输入边界、空值、分页、并发、幂等、软删除与恢复是否有明确行为。
- API schema、service、数据库模型、迁移、Web 调用和 MCP 工具是否保持契约一致。
- 权限是否同时覆盖正常授权与越权拒绝，human/agent 是否按角色同等判权。
- 错误是否使用 Zeichen 的四类语义：`permission_denied`、`not_found`、`conflict`、`invalid_request`。
- 变更是否保留 activity、来源、项目隔离和追溯关系。

## 前端约定

- 每个新增或修改的 `Input`、`Textarea`、原生 `input`/`textarea` 是否显式声明语义正确的 `autoComplete`。
- 现有密码使用 `current-password`；创建、设置或确认新密码使用 `new-password`；无合适标准语义时使用 `off`。
- 非模态页面的操作、接口和加载失败是否通过可关闭的 `ErrorNotification` 呈现，根部是否保留 `NotificationProvider`。
- 对话框内校验或提交错误是否只在对话框内呈现，避免对话框外重复通知。
- React Query 缓存更新、失效和错误恢复是否让界面与服务端状态一致。
- 键盘、焦点、标签、禁用态和破坏性操作确认是否可用。

## 后端与数据

- FastAPI 输入输出 schema 与 service 约束是否匹配，异常是否被映射为稳定的公开错误。
- 查询是否强制项目可见性与角色判权，是否存在 IDOR 或跨项目数据泄露。
- 指派任务的本人/管理员规则、评论删除规则和 viewer 只读规则是否保持。
- 软删、restore、关联对象影响及二次确认数量是否正确。
- 新字段或约束是否有可升级、可回滚、兼容既有数据的 Alembic 迁移。
- 时间、UUID、cursor、事务和并发写入是否稳定。

## MCP 与产品语义

- Web 与 MCP 是否表达同一个领域行为，工具参数、返回值和错误是否与规格一致。
- 需求四态、任务五态是否允许自由流转；任务状态是否错误地自动改变需求状态。
- Zeichen 是否保持“只记录、不调度”的边界。
- 每项目一个共享记忆 Dataset、会话命名空间、来源展示和权限是否正确。
- 记忆操作是否错误复制业务实体可变状态，或绕过项目隔离。

## 验证命令

根据范围选择，避免无意义地全跑：

- 前端单测：`npm test -- --run <相关测试>`（在 `frontend/`）
- 前端 lint：`npm run lint`（在 `frontend/`）
- 前端构建与类型检查：`npm run build`（在 `frontend/`）
- 后端单测：`pytest <相关测试文件或节点>`（在 `backend/`，使用项目环境）
- 全量后端测试：`pytest`（仅在改动面较广或交付前）

把环境缺失、外部服务不可用和产品缺陷分开记录。仅当失败可归因到 Zeichen 本身且达到 SKILL.md 的证据门槛时提需。
