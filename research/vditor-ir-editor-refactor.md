# Vditor IR 模式 Markdown 编辑器重构调研

调研日期：2026-08-04  
调研范围：仅参考 Vditor 的 **IR（即时渲染）** 模式，目标为单一、实时渲染的 Markdown 编辑体验；不包含分屏预览、源码模式或富媒体扩展。

## 结论

将编辑器重构为一个以 Markdown 字符串为唯一持久化值的 `VditorIrEditor` 组件：初始化时固定 `mode: 'ir'`，编辑时通过 `input(markdown)` 向页面状态上报，保存时提交该 Markdown，卸载时调用 `destroy()`。阅读页也应复用 Vditor 的静态 Markdown 渲染能力或与其等价、统一的渲染管线，避免编辑与阅读各自解析同一份 Markdown。

Vditor 官方将 IR 定位为类似 Typora 的“即时渲染”模式；它与 WYSIWYG、分屏预览并列，但可在初始化选项中单独指定。IR 实现创建一个 `contenteditable` 编辑面，并在输入、粘贴、选择、快捷键和 IME 组合输入事件中维护 Markdown 标记与实时呈现。[[S1]] [[S2]]

## 严格的功能边界

首个版本只支持下列基础 Markdown，工具栏应采用白名单，而不是继承 Vditor 的默认工具栏：

| 支持 | 建议 Vditor 工具栏项 |
| --- | --- |
| 标题 | `headings` |
| 加粗、斜体、删除线 | `bold`、`italic`、`strike` |
| 引用、分隔线 | `quote`、`line` |
| 无序/有序列表 | `list`、`ordered-list` |
| 链接 | `link` |
| 行内代码、代码块 | `inline-code`、`code` |
| 撤销、重做 | `undo`、`redo` |

任务列表 `check` **不纳入本期**；它是 GFM 扩展而非严格基础 Markdown，后续仅在产品确认需要可点击任务时再增加。官方默认工具栏中同时提供上述基础项和大量不在范围内的项目，因此必须显式配置 `toolbar`。[[S3]]

明确排除：

- Vditor 的 `sv` 分屏预览、`wysiwyg` 模式、模式切换（`edit-mode`）与预览切换（`both`、`preview`）；页面不出现源码面板或双栏布局。[[S1]] [[S3]]
- 表格、图片/文件上传、录音、表情、自动补全、评论、导出、开发工具、内容/代码主题选择、目录、全屏与各类预览动作。
- 数学公式、Mermaid/流程图/甘特图/图表/脑图/Graphviz/PlantUML、五线谱、媒体嵌入以及其他 Markdown 扩展。虽然 Vditor 支持它们，但它们不属于本次“基础 Markdown”契约。[[S1]]
- 客户端草稿缓存与“实时保存”作为默认行为；应继续以项目既有的显式保存与服务端版本语义为准。Vditor 的缓存默认开启，且在启用时要求显式 `cache.id`，因此若不需要草稿恢复应明确设为 `cache: { enable: false }`。[[S3]]

## 推荐的组件接口与生命周期

```ts
type VditorIrEditorProps = {
  initialMarkdown: string
  onChange(markdown: string): void
  onReady?(editor: Vditor): void
  disabled?: boolean
}
```

1. React `useEffect` 仅在承载元素可用时创建一个实例：`new Vditor(host, { mode: 'ir', value: initialMarkdown, input, after, toolbar, cache: { enable: false } })`。
2. `after` 标记编辑器可交互；创建前与创建中展示页面级加载状态，避免用户向尚未就绪的 `contenteditable` 输入。官方将 `after` 定义为“编辑器异步渲染完成后的回调”。[[S1]]
3. `input(value)` 只把 Markdown 回传给 React 状态；不要在每次输入后重新创建实例或用 `setValue` 回灌，否则会破坏选区、撤销栈和 IME 组合输入。IR 源码专门处理 `compositionstart`/`compositionend` 和输入事件。[[S2]]
4. 文档切换或从服务端收到“非本地编辑”更新时才调用 `setValue(markdown, true)`；第二个参数清空历史栈，适合作为外部重置而不是日常受控渲染。`getValue`、`setValue`、`disabled`、`enable` 和 `destroy` 都是官方公开方法。[[S1]]
5. effect 清理函数必须调用 `destroy()`；保存前调用 `getValue()` 作为最终值读取（或使用已同步的状态），并在请求期间使用 `disabled()` 防止重复提交，完成后 `enable()`。[[S1]]

## 实施与验收重点

- 将当前编辑器适配层独立为组件，编辑页只负责标题、脏状态、保存/离开确认和 API 调用；不要将 Vditor 实例放入全局状态或作为 React 受控 DOM 重绘。
- 通过包管理器锁定 `vditor` 版本并导入其 CSS；官方默认 `cdn` 指向 unpkg，若功能会按需加载资源，生产环境必须显式配置受控的同版本静态资源地址，避免依赖无版本的第三方运行时资源。[[S1]] [[S3]]
- Vditor IR 使用原生 `contenteditable`，源码可见其根元素未提供 ARIA 角色或名称配置。因此页面必须提供可见 `Label`/说明、明确的焦点样式、键盘可达工具栏按钮和快捷键提示，并用 NVDA/VoiceOver 与键盘逐项验收；不要把“编辑器可输入”等同于无障碍完成。[[S2]]
- IR 的格式化处理在输入事件中执行，并对 IME 组合输入单独加锁；上线前使用真实长文档、中文输入、粘贴和撤销/重做测量输入延迟。若需要节流，只节流脏状态/自动保存，不能延迟编辑器内部渲染或丢弃最终 `input` 值。[[S2]]
- 失败反馈继续符合项目约定：页面级加载/保存/API 失败使用可关闭的 `ErrorNotification`；新增的标题等表单控件必须声明语义正确的 `autoComplete`。

## 最小验收用例

1. 输入各项允许的基础语法，光标附近立即呈现相应样式；保存、重新打开和阅读页显示一致。
2. 页面中不存在分屏、预览/源码/模式切换、上传、表格、公式、图表或媒体入口；粘贴这些不支持的复杂语法时按普通 Markdown 文本安全保留或按产品规则提示，不能悄然生成不受支持的富内容。
3. 中文 IME 连续输入、粘贴、撤销/重做、链接编辑、文档切换和保存中禁用/恢复均不丢内容或移动选区。
4. 只用键盘可完成焦点进入编辑区、使用工具栏、保存和返回；辅助技术能识别编辑区名称与工具栏按钮名称。

## 第一方来源

- [S1] [Vditor 官方仓库 README](https://github.com/Vanessa219/vditor/blob/master/README.md)：三种模式、功能范围、`new Vditor` 初始化、选项、工具栏和公开方法文档。
- [S2] [IR 实现源码](https://github.com/Vanessa219/vditor/blob/master/src/ts/ir/index.ts)：`contenteditable` 编辑面、输入/IME/粘贴/键盘/选择处理。
- [S3] [默认选项与工具栏源码](https://github.com/Vanessa219/vditor/blob/master/src/ts/util/Options.ts)：默认 `mode: 'ir'`、缓存、CDN、预览配置、默认工具栏和快捷键。
