# Markdown 文档编辑器实现调研

调研日期：2026-08-04  
调研范围：官方 GitHub 仓库及仓库内维护的文档；关注 React、Markdown/WYSIWYG、文档编辑页面工作流。  
结论：**继续采用 Milkdown，不更换编辑器；把创建与编辑迁至独立路由页面，并将 Wiki、词条、API 作为左侧「文档」的可折叠子导航。**

---

## 1. 成熟实现的共同做法

成熟编辑器都把「编辑器实例」嵌进一个页面容器，而不是把完整编辑体验限制在新建/编辑弹窗中；页面负责标题、保存、返回、版本等工作流，编辑器负责正文状态与格式化。对于 Markdown 产品，最关键的设计决策是**持久化格式**：编辑器的内部文档模型不等于后端保存格式。

| 方案 | 官方实现要点 | 与本项目 Markdown 版本链的匹配度 |
| --- | --- | --- |
| Milkdown | 插件驱动的 WYSIWYG Markdown 编辑器，基于 ProseMirror 与 remark；官方提供 React 集成包。[[M1]] [[M2]] | **高**：正文可继续以 Markdown 字符串保存，符合当前文档版本、回滚与 MCP 接口。 |
| TOAST UI Editor | 同时提供 Markdown 与 WYSIWYG 模式，可切换；Markdown 模式提供实时预览、滚动同步，并有 React wrapper。[[T1]] [[T2]] | 高：若产品明确需要「源码 + 双栏预览」可考虑，但迁移现有 Milkdown 没有必要。 |
| BlockNote | React 的块编辑器；Markdown 导入/导出均被官方标为有损，建议后端无损持久化其 Blocks JSON。[[B1]] [[B2]] | 低：改用它会使「Markdown 是版本真相」不再成立，复杂 Markdown 可能在来回转换后丢失信息。 |
| Editor.js | 块编辑器保存的是干净 JSON，非 Markdown；每个 Block 由工具插件提供。[[E1]] | 低：需要另做 Markdown 双向转换及语义约束，不适合作为本票的默认方案。 |

## 2. 对当前实现的判断

当前 `frontend/src/pages/documents.tsx` 已使用 `@milkdown/react`、`commonmark`、`listener` 与 Nord 主题；通过 `markdownUpdated` 将编辑状态回写为 Markdown 字符串，再由现有文档 API 保存。这与 Milkdown 的「WYSIWYG Markdown」定位一致，**应保留**。

但目前编辑器位于「新建/编辑」对话框内，空间受限、无法承载工具栏/保存状态/版本入口等文档工作流；同时列表页顶部的 Wiki/字典/API 横向切换与应用左侧导航重复。阅读页还使用了一个仅覆盖标题和列表的手写 `Markdown` 渲染器，显示语义与编辑器支持的 CommonMark 范围不一致。

## 3. 推荐的信息架构与路由

把左侧栏的「文档」改为可折叠父项；父项只负责展开/收起，三个子项才是内容入口。移除文档列表页内重复的横向类型 Tab。

```text
工作区
  文档  [展开/收起]
    Wiki       -> /documents/wiki
    词条       -> /documents/glossary
    API 定义   -> /documents/api

/documents/:type                 类型列表（新建按钮）
/documents/:type/new             专用创建编辑器
/documents/:id                   阅读、版本、删除、引用
/documents/:id/edit              专用编辑器
```

列表与详情均根据 URL 得到文档类型；因此刷新、复制链接、前进/后退都不会丢失当前类型。旧的 `/documents` 可重定向到 `/documents/wiki`，保证旧链接可用。

## 4. 专用编辑器页面建议

新建和编辑共用 `DocumentEditorPage`，不要在 `Dialog` 中渲染 `DocumentForm`。页面应采用以下职责划分：

1. 顶栏：返回列表、文档类型、保存状态、取消/保存；编辑已有文档时提供「版本历史」入口或返回详情页入口。
2. 主编辑区：标题输入框 + Milkdown 全宽正文；API 文档在正文下方或右侧保留端点与 Schema 表单。保存时仍提交 Markdown 与现有 metadata，不改变后端版本语义。
3. 提交失败：使用项目约定的可关闭 `ErrorNotification`；表单控件继续显式标记 `autoComplete`。
4. 阅读一致性：阅读页应改用同一 Markdown 解析/渲染体系（至少完整 CommonMark/GFM），不要继续维护手写的有限行级渲染器；避免「编辑器可写、阅读页不能正确显示」的差异。
5. 交互保护：保存按钮只在提交时禁用；若以后增加自动保存或离页确认，仍以服务器返回的版本为准，避免本地状态伪造版本号。

此方案延续当前「显式保存即创建版本」规则。若未来需要源码编辑体验，可在 Milkdown 页面增设可选的 Markdown 源码/预览模式；在未明确提出该需求前，不应为此迁移到 TOAST UI。

## 5. 验收建议

- 访问 `/documents/wiki`、`/documents/glossary`、`/documents/api` 时左侧对应子项高亮，父项可折叠；列表页无重复类型 Tab。
- 「新建」进入 `/documents/:type/new`，不出现编辑对话框；保存成功跳转详情，且产生第一个版本。
- 「编辑」进入 `/documents/:id/edit`；保存仍创建新版本，取消/返回不提交变更。
- 使用标题、列表、代码块、链接、表格等 Markdown 样例，验证编辑后保存、详情阅读、版本回滚三处内容一致。
- API Schema 输入及所有新增输入控件均带合适的 `autoComplete`；页面级加载/接口错误由可关闭的 `ErrorNotification` 展示。

## 来源（均为第一方）

- [M1] Milkdown 官方仓库 README：其定位为「插件驱动的 WYSIWYG Markdown 编辑器」，并说明构建于 ProseMirror 与 remark。<https://github.com/Milkdown/milkdown/blob/main/README.md>
- [M2] Milkdown 官方 React 集成包。<https://github.com/Milkdown/milkdown/tree/main/packages/integrations/react>
- [T1] TOAST UI Editor 官方仓库 README：Markdown/WYSIWYG 双模式、实时预览、滚动同步与插件说明。<https://github.com/nhn/tui.editor/blob/master/README.md>
- [T2] TOAST UI Editor 官方 React wrapper：`initialValue`、`initialEditType`、实例获取及事件 props。<https://github.com/nhn/tui.editor/blob/master/apps/react-editor/README.md>
- [B1] BlockNote 官方仓库 README：React 块编辑器及其 React 接入示例。<https://github.com/TypeCellOS/BlockNote/blob/main/README.md>
- [B2] BlockNote 官方 Markdown 导入/导出文档：两方向均可能有损，官方建议无损持久化 Blocks JSON。<https://github.com/TypeCellOS/BlockNote/blob/main/docs/content/docs/features/import/markdown.mdx>；<https://github.com/TypeCellOS/BlockNote/blob/main/docs/content/docs/features/export/markdown.mdx>
- [E1] Editor.js 官方仓库 README：块插件模型及 JSON 输出。<https://github.com/codex-team/editor.js/blob/next/README.md>
