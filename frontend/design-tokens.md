# Zeichen 设计 token 定稿(v1.0)

> REQ-6「UI 打磨:明暗主题切换 + 视觉样式模板定稿」交付物。
> 单一事实来源:`frontend/src/index.css`(Tailwind v4,`@theme inline` + `:root` / `.dark` 双变量块)。
> 全站样式一律引用本文所列语义 token;禁止绕开语义 token 直接使用硬编码调色板色类(除非为同一元素补齐 `dark:` 配对并经裁决)。

## 1. 总则

- 样式体系:Tailwind CSS v4(CSS-first 配置),暗色变体基于 `.dark` 类切换:`@custom-variant dark (&:is(.dark *))`,非 `prefers-color-scheme` 媒体查询。
- 主题状态:`html` 根元素 `.dark` 类;默认浅色,由 `ThemeProvider`(`@/lib/theme`)切换并持久化到 `localStorage`(键 `zeichen.theme`,值 `light` / `dark`);不做跟随系统。
- 两套配色(浅色/暗色)均以 oklch 定义;所有语义变量在 `:root` 与 `.dark` 中成对定义,组件层只消费语义类(`bg-background`、`text-muted-foreground` 等)。
- 字体:Geist(`@fontsource-variable/geist`),无衬线全局应用,`--font-heading` 与 `--font-sans` 同源。

## 2. 色彩

### 2.1 语义变量索引

| 语义 token | 用途 | 浅色(oklch) | 暗色(oklch) |
| --- | --- | --- | --- |
| `--background` / `--foreground` | 页面底色 / 正文 | 1 0 0 / 0.145 0 0 | 0.145 0 0 / 0.985 0 0 |
| `--card` / `--card-foreground` | 卡片 | 1 0 0 / 0.145 0 0 | 0.205 0 0 / 0.985 0 0 |
| `--popover` / `--popover-foreground` | 浮层(菜单/对话框) | 1 0 0 / 0.145 0 0 | 0.205 0 0 / 0.985 0 0 |
| `--primary` / `--primary-foreground` | 主操作 | 0.205 0 0 / 0.985 0 0 | 0.922 0 0 / 0.205 0 0 |
| `--secondary` / `--secondary-foreground` | 次级操作 | 0.97 0 0 / 0.205 0 0 | 0.269 0 0 / 0.985 0 0 |
| `--muted` / `--muted-foreground` | 弱化底 / 弱化文本 | 0.97 0 0 / 0.556 0 0 | 0.269 0 0 / 0.708 0 0 |
| `--accent` / `--accent-foreground` | 悬停强调 | 0.97 0 0 / 0.205 0 0 | 0.269 0 0 / 0.985 0 0 |
| `--destructive` | 危险操作/错误 | 0.577 0.245 27.325 | 0.704 0.191 22.216 |
| `--border` | 描边 | 0.922 0 0 | 1 0 0 / 10% |
| `--input` | 输入描边 | 0.922 0 0 | 1 0 0 / 15% |
| `--ring` | 聚焦环 | 0.708 0 0 | 0.556 0 0 |
| `--chart-1` … `--chart-5` | 图表序列 | 灰阶 0.87→0.269 | 与浅色一致 |
| `--sidebar` 系列 | 侧边栏底/文本/主色/强调/描边/环 | 见 index.css `:root` | 见 index.css `.dark` |

### 2.2 状态色(明暗配对)

状态徽章、状态点使用调色板色时必须明暗成对(浅 `-500`/`-600`、暗 `-400` 提亮),与暗色下更亮的文本适配一致:

| 状态 | 徽章(浅色) | 徽章(暗色) | 状态点(浅色) | 状态点(暗色) |
| --- | --- | --- | --- | --- |
| 待确认 pending | violet-500/10 + violet-600 | violet-500/15 + violet-400 | violet-500 | violet-400 |
| 进行中 in_progress | blue-500/10 + blue-600 | blue-500/15 + blue-400 | blue-500 | blue-400 |
| 验收中 verifying | amber-500/10 + amber-600 | amber-500/15 + amber-400 | amber-500 | amber-400 |
| 已完成 done | green-500/10 + green-600 | green-500/15 + green-400 | green-500 | green-400 |
| 待办 backlog / 已取消 cancelled | `--muted` / `--destructive` 语义 token | 同左 | `--muted-foreground` / `--destructive` | 同左 |

成功反馈用 emerald(emerald-600/30 级别,暗色配 emerald-400/40),警示用 amber(暗色配 -400)。`bg-black/N` 类遮罩须补 `dark:bg-black/N′` 配对(暗色加深)。

### 2.3 使用规则

1. 组件样式只允许语义 token 类与上述状态色配对;新色调先入表再使用。
2. `:root` / `.dark` 双块必须同步维护,新增变量两套配色都要定义。
3. 覆盖 Tailwind 调色板类(如 `bg-emerald-700`)而无 `dark:` 配对视为违规(`dark-palette.test.ts` 全站扫描)。

## 3. 字体

| token | 值 | 用途 |
| --- | --- | --- |
| `--font-sans` | `'Geist Variable', sans-serif` | 全局正文(`html { @apply font-sans }`) |
| `--font-heading` | `var(--font-sans)` | 标题与正文同字体,层级靠字重/字号区分 |

- 字体源:`@fontsource-variable/geist`(可变字重,随前端打包,无外部请求)。
- 正文字号 `text-sm`(14px)为界面默认;辅助文本 `text-xs`;页面主标题 `text-base`/`text-lg` + `font-semibold`。
- 标题字距:大标题 `-0.025em`(见 index.css 文档编辑器 h1–h3 规则)。

## 4. 圆角

基准 `--radius: 0.625rem`(10px),派生刻度由 Tailwind v4 `@theme inline` 计算:

| token | 计算 | 值(≈) |
| --- | --- | --- |
| `rounded-sm` | `--radius * 0.6` | 6px |
| `rounded-md` | `--radius * 0.8` | 8px |
| `rounded-lg` | `--radius` | 10px(按钮/输入/菜单默认) |
| `rounded-xl` | `--radius * 1.4` | 14px(卡片/对话框) |
| `rounded-2xl` | `--radius * 1.8` | 18px |
| `rounded-3xl` | `--radius * 2.2` | 22px |
| `rounded-4xl` | `--radius * 2.6` | 26px |

使用规则:交互控件(按钮/输入)用 `rounded-lg` 级;容器(卡片/对话框/通知)用 `rounded-xl` 级;圆点/徽标可用 `rounded-full`。

## 5. 密度

| 维度 | 定稿值 |
| --- | --- |
| 控件高度 | `sm`=28px(h-7)、默认=32px(h-8)、`lg`=36px(h-9);图标钮 `icon-sm`=28px |
| 页面留白 | 主内容区 `p-6`(24px);侧边栏区块 `p-2`;卡片内 `p-4`–`p-5` |
| 表单密度 | 标签与控件间距 `space-y-1.5`;分组间距 `space-y-4`/`space-y-5` |
| 列表/表格 | 行高以 `py-2`–`py-3` 为基准;分组标题 `text-[11px]` 大写字距标签 |
| 侧边栏宽度 | 固定 `w-52`(208px),不随主题变化 |

密度不随明暗主题切换;两套配色共用同一布局密度。

## 6. 与明暗主题的联动验收

1. 默认浅色;顶栏控制区「切换主题」按钮点击后 `html.classList` 切换 `.dark` 并持久化;二次进入页面(含首帧内联脚本)保持所选主题,无闪烁。
2. 两套配色下逐页走查:背景/前景、边框、悬停态、聚焦环、状态徽章、通知、对话框遮罩均使用语义 token 呈现,无硬编码色残留(全站扫描用例持续守护)。
