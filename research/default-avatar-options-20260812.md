# 默认头像方案调研

调研日期：2026-08-12
范围：DiceBear、Boring Avatars、Gravatar 默认图与本地 Identicon；只引用官方文档、官方源码和许可证原文。

## 结论

Zeichen 最适合采用 **Boring Avatars 的 `pixel` 或 `beam` 变体，在前端本地生成 SVG**。它比单个首字母更像真正的头像，又不至于像完整卡通人物那样抢夺页面注意力；同一用户始终得到同一图形；没有头像网络请求；依赖与实现都很小；代码和图形实现均在单一 MIT 许可证下，合规边界最清楚。[S4][S5][S6]

建议默认使用 `pixel`，以 Zeichen 自有的 5～8 色调色板统一视觉；如果希望更柔和、更具人物感，改用 `beam`。种子使用稳定且不公开敏感信息的值，例如 `zeichen:user:<user_id>`，不要使用昵称（可修改）或邮箱（隐私敏感）。用户上传真实头像后，上传头像始终覆盖生成头像。

DiceBear 适合作为以后希望提供“头像风格选择器”时的升级方案：它有 52 种从抽象图形到角色插画的风格和大量可配置部件，但需要核心包与风格定义，并且每种风格有各自的许可证，实施和合规成本都明显更高。[S1][S2][S3]

不建议把 Gravatar 或其 `identicon` 作为默认方案。它接入代码很少，但浏览器每次会向外部服务请求图片；标识来自规范化邮箱的 SHA-256，用户更换邮箱也会改变默认头像。外部请求还会使服务方接收到普通 Web 请求伴随的 IP、浏览器、来源页等信息，且可用性受第三方服务影响。[S9][S10][S11]

## 对比

| 方案 | 视觉趣味 | 确定性 | 隐私与网络 | 依赖/资源 | 授权风险 | 实现成本 |
| --- | --- | --- | --- | --- | --- | --- |
| **Boring Avatars `pixel` / `beam`** | 中高；6 个抽象变体，可用品牌色定制 | 名称/种子、变体和调色板相同则结果稳定 | React 内直接渲染 SVG，无外部图片请求 | 一个 React 包；项目已有 React 19，满足其 React 18+ peer dependency | **低**；MIT 单一许可证 | **低**；一个共享头像组件即可 |
| **DiceBear 本地库** | **最高**；52 种风格，抽象、像素、机器人、人物均有 | 同一 seed、style、options 生成同一 SVG | 本地生成时无第三方请求；也可自托管 | JS 方案使用 core 加选定的 styles；功能面更大 | **中高**；核心 MIT，但各 style 许可证不同，部分要求署名 | 中；需选定、锁定风格和选项并处理署名 |
| **本地 Identicon.js** | 中低；经典对称像素几何，辨识度高但偏开发者工具气质 | 输入同一 15+ 位十六进制 hash 得到同一图形 | 本地生成，无外部请求 | 单个 JS 库；SVG 不需 PNGLib，PNG 需要额外 PNGLib | 低；BSD 2-Clause，需保留声明 | 低到中；调用前还要自行产生稳定 hash |
| **Gravatar `d=identicon` 等** | 中；还提供 monsterid、wavatar、retro、robohash 等托管默认图 | 由规范化邮箱 SHA-256 决定；邮箱变化即变化 | **有第三方请求**；向 Gravatar 发送邮箱 hash，并暴露请求元数据 | 无本地头像库，但依赖网络与第三方可用性 | 服务条款边界，不是本地开源生成器的简单 MIT 依赖 | 代码最低，产品/隐私成本较高 |

## 方案细节

### 1. Boring Avatars：推荐

官方将其定义为从用户名、邮箱或任意字符串生成唯一 SVG 用户头像的 React 库，提供 `marble`、`beam`、`pixel`、`sunset`、`ring`、`bauhaus` 六种变体，并允许自定义调色板。[S4] 源码的 `hashCode(name)` 是纯字符串散列，各变体据此选择颜色和几何参数，所以固定种子、变体和颜色后结果是确定的。[S5]

它与 Zeichen 的适配点：

- 项目已有 React，无需引入 Canvas、图片处理或服务端存储流程；包声明的 peer dependency 是 React/ReactDOM 18 以上。[S6]
- SVG 由组件本地渲染，头像列表不会产生逐用户的第三方图片请求。
- `pixel` 在 32～40 px 仍容易区分，适合成员列表和评论；`beam` 更像抽象人物，适合个人资料弹窗的大尺寸预览。
- 自有调色板可以减少随机颜色与现有 UI 的冲突，仍保留不同用户的视觉差异。
- MIT 许可证允许使用、修改与分发，但分发代码或实质部分时仍应保留版权与许可声明。[S7]

建议不要直接把登录账号或邮箱传给组件。共享组件只接收后端稳定的用户 ID，并在前端拼接固定命名空间。这样昵称变化不会让头像突变，也避免把邮箱放进组件属性、DOM 或图片 URL。

### 2. DiceBear：丰富但更重

DiceBear 官方说明任意 seed 都可以生成确定性的 SVG，当前提供 52 种风格；同一 seed 始终产生同一头像，还能调整背景、颜色、旋转和具体部件。[S1] JavaScript 用法是导入核心库与某个风格定义后生成 SVG 字符串或 data URI；官方也提供无认证 HTTP API和自托管 API。[S1][S2]

若使用 DiceBear，应采用本地 JavaScript 库或自托管实例，而不是公共 API。官方明确公共 API 不能保证永远可用或输出永远不变，并建议对可用性、限流和数据隐私有要求时自行托管。[S2]

最大风险不是核心代码：核心是 MIT，但官方明确每个头像风格由作者单独选择许可证；有 CC0、MIT、CC BY 4.0 以及作者自定条款等差异。[S3] 因此不能看到“DiceBear 是 MIT”就默认所有生成头像都没有署名义务。若将来采用，必须固定具体 style 和版本，在产品或开源声明里记录该 style 的许可证与归属。

### 3. 本地 Identicon：轻量但不够有趣

Identicon.js 的官方仓库说明它根据至少 15 位十六进制 hash 生成 GitHub 风格的 PNG 或 SVG；相同 hash 得到相同形状和近似颜色。可配置尺寸、边距、前景/背景、饱和度和亮度；SVG 无需 PNG 输出所需的 PNGLib。[S8]

这个方案完全本地、稳定、体积小，适合机器账号、内容指纹或开发者工具。不过其对称几何语言更像“对象标识”而非“人物身份”，相较 `pixel`/`beam` 改善了单字母占位，却没有明显增加亲和感。许可证为 BSD 2-Clause，分发时要保留版权、条件与免责声明。[S8]

### 4. Gravatar：不适合默认启用

Gravatar 官方流程要求先把邮箱 trim、转小写，再做 SHA-256，将 hash 放入 `https://gravatar.com/avatar/<hash>`；默认图参数可选 `identicon`、`monsterid`、`wavatar`、`retro`、`robohash` 等。[S9][S10]

这带来三个产品问题：

1. 默认头像身份绑定在邮箱而非 Zeichen 用户 ID 上，换邮箱会换图。
2. 每次图片加载依赖外部域名；内网、离线或服务不可用时会失败。
3. 即使 URL 中不是明文邮箱，它仍包含邮箱派生的 hash。Automattic 的官方隐私政策说明其服务会自动收集 IP、浏览器类型、唯一设备标识、语言、来源站点、访问时间、操作系统和移动网络等使用信息。[S11]

因此 Gravatar 更适合作为用户主动选择的头像来源，而不是所有未上传头像用户的默认行为。

## 推荐落地规则

1. 头像优先级：上传头像 → 本地生成头像；移除头像后立即恢复同一生成头像。
2. 生成种子：`zeichen:user:<immutable_user_id>`。为 Agent 使用不同命名空间，如 `zeichen:agent:<agent_id>`，避免相同数字 ID 碰撞。
3. 固定 `pixel` 变体和品牌调色板，不按页面随机变体；否则同一用户会在不同位置看起来像不同身份。
4. 共享一个 `Avatar` 组件，列表、评论、侧栏和资料弹窗统一使用，避免任何位置退回首字母文本。
5. SVG 仅作装饰且旁边已有可见昵称时从辅助技术隐藏；独立显示时提供与用户/Agent 对应的可访问名称。
6. 锁定 npm 版本，并以可视化快照测试保证依赖升级不会悄然改变所有默认头像。

## 一手来源

- [S1] [DiceBear 官方仓库 README](https://github.com/dicebear/dicebear/tree/10.x)：52 种风格、seed 确定性、跨语言一致输出、本地库用法及核心许可证说明。
- [S2] [DiceBear HTTP API 官方文档](https://www.dicebear.com/how-to-use/http-api/)：稳定 ID 作 seed、公共 API 可用性/输出承诺、自托管建议、格式和限流。
- [S3] [DiceBear 官方许可证清单](https://www.dicebear.com/licenses/) 与 [核心 MIT 许可证原文](https://github.com/dicebear/dicebear/blob/10.x/LICENSE)：代码与各 style 的许可证边界。
- [S4] [Boring Avatars 官方 README](https://github.com/boringdesigners/boring-avatars)：SVG、本地 React 用法、6 个变体和颜色参数。
- [S5] [Boring Avatars 官方散列与生成源码](https://github.com/boringdesigners/boring-avatars/blob/master/src/lib/utilities.ts)：名字到颜色/几何参数的确定性映射。
- [S6] [Boring Avatars 官方 package.json](https://github.com/boringdesigners/boring-avatars/blob/master/package.json)：包结构与 React peer dependency。
- [S7] [Boring Avatars MIT 许可证原文](https://github.com/boringdesigners/boring-avatars/blob/master/LICENSE)。
- [S8] [Identicon.js 官方 README 与许可证说明](https://github.com/stewartlord/identicon.js)：输入 hash、SVG/PNG 输出、选项、PNG 依赖及 BSD 许可；[BSD 许可证原文](https://github.com/stewartlord/identicon.js/blob/master/LICENSE)。
- [S9] [Gravatar 官方头像 API 文档](https://docs.gravatar.com/api/avatars/images/)：头像 URL 和默认图类型。
- [S10] [Gravatar 官方邮箱 Hash 规范](https://docs.gravatar.com/api/avatars/hash/)：trim、转小写与 SHA-256。
- [S11] [Automattic 官方隐私政策](https://automattic.com/privacy/)：自动收集的请求与设备信息。

注：本次环境访问 Gravatar 文档站时连接不稳定；相关事实由其官方文档 URL 和官方隐私政策交叉核对，不引用第三方教程或测评。
