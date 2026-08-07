# 17 跨语言代码签名文本输入

Status: planned
Type: enhancement
Priority: medium
Blocked by: none

## 目标

为 `docs.code.create` / `docs.code.update` 增加可选的签名文本输入能力，使 agent 可以提交 Python、C# 等代码声明，并可靠地转换为现有的结构化 `definition`。

## 当前边界

- 当前版本只接受结构化 `definition.parameters`、`definition.returns` 等字段。
- 传入未受支持的 `signature` 字段会明确返回 `invalid_request`，不得静默忽略或用空参数替代。
- 本票不改变当前结构化写入契约。

## 范围与验收

- 明确定义支持的语言、声明种类和语法子集；不支持的文本必须返回可操作的 `invalid_request`。
- 解析结果必须与结构化写入使用同一校验、唯一性、版本和权限路径。
- 解析失败不得写入部分符号，也不得丢失参数、泛型、传参方式或返回类型。
- 覆盖 Python 函数、C# 方法/构造函数、泛型和非法输入的 MCP 回归测试。
- 在工具 input schema 与文档中明确结构化模式和签名文本模式，避免两者同时提供时的歧义。
