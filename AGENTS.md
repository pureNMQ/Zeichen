# 开发约定

## 表单输入

- 禁止提交未显式声明 `autoComplete` 的裸 `<Input>`、`<Textarea>` 或原生 `<input>`/`<textarea>`。
- 所有非密码输入必须使用与字段语义相符的 `autoComplete` 值；没有合适的标准语义时必须写 `autoComplete="off"`，不能依赖浏览器猜测。
- 密码输入必须明确使用 `autoComplete="current-password"`（验证现有密码/登录）或 `autoComplete="new-password"`（创建、设置或确认新密码）。
- 表单评审时检查每个新增或修改的输入控件均符合以上规则。

## 提示与错误反馈

- 页面内不得以普通文本（例如 `text-destructive` 的 `<p>` 或 `<span>`）显示操作失败、接口失败或加载失败的提示。
- 非模态页面中的上述反馈统一使用 `ErrorNotification`；应用根部必须保留 `NotificationProvider`，通知必须可关闭。
- 对话框内的表单校验或提交错误可以保留在该对话框中；不要在对话框外额外渲染同一错误。
