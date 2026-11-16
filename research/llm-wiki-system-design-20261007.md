# 设计稿：LLM Wiki 系统改造（2026-10-07）

> 状态：**草案 v3，讨论中，未定稿**（已合入 D1–D6 与附件裁定、pg_trgm 更正、Cline 参考、
> D7 三路线分析；余一项待决 D7，裁定后定稿并重写 W3）。
> 对应计划二。本文先解释概念与能力分层，再给技术方案、分期与决策点清单。

## 决策进展（2026-10-07 与用户对齐）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 嵌入/语义检索 | **不做**（用户裁定：语义检索不可靠、易引入大量不相关文档；关键词检索最好，LLM 自己挑选的关键词比语义召回更精确） |
| D2 | 向量存储 | 随 D1 取消——不引入 pgvector，**不更换 postgres 镜像**（pg_trgm 为自带 contrib，`CREATE EXTENSION` 即可） |
| D3 | 分词/索引 | **更正原稿**：`tsvector simple` 对中文不适用（中文无空格分隔，simple 配置把整段中文当成单个 token，全文索引对中文基本失效）。纯关键词方案正解为 **pg_trgm 三元组索引**：保持现有 ILIKE 子串匹配语义不变，GIN 索引加速，相关度用 trigram 相似度排序 |
| D4 | 摘要来源 | **B 创作时写**（2026-10-07 裁定）：agent/人保存文档时在 frontmatter 自带 `summary:`，后端只解析与返回、缺省回退开头截断；后端保持零 LLM 依赖；存量 61 篇回退截断，可由一次性 agent 任务补写 |
| D5 | 双链时机 | **做，写入时落表**（2026-10-07 裁定）：`[[DOC-n]]`/`[[标题]]` 写入正文，create/update/rollback 时解析落 `doc_link` 表；反链即时查询、保存时断链警告、context 沿链扩展；存量零回填 |
| D6 | 一期范围 | **溯源标识 + 过期检测进一期**（2026-10-07 裁定，均为「不错的功能」）；**体检报告不做**（用户裁定：「好」的标准难制定且收益不大——若二期需要再议）。一期 = W1 结构层 + W2 检索层 + W3 组装层 + 溯源 + 过期检测 |
| D7 | wiki.context 组装接口 | **讨论中**：三选一待裁定（甲 不做组装、强化探索面 / 乙 做且限单项目 / 丙 做且跨项目），详见 §5.6 |
| — | 附件检索 | **不进**（2026-10-07 裁定：无「搜附件内容」实际场景记录；PDF 解析引入依赖） |

生产现状实测（2026-10-07，只读统计）：wiki 61 篇、glossary 27 词条；metadata 非空 0 篇；
正文含 `[[` 的 0 篇；平均正文 3977 字，最长 42215 字。

## 1. 现状与问题

Zeichen 文档系统现状（v0.3.0）：

- 模型：`Document`（wiki 树 + glossary 词条，复合主键 (project_id, code)，DOC-n/TERM-n 短码）
  + `DocumentDirectory`（仅 glossary）+ `DocumentVersion`（全量版本）；
- 关联：实体引用 `derives/documents/implements/mentions`（需求↔文档↔仓库），评论区，附件；
- 检索：`search.query` 对 title/content 做 **ILIKE 字面子串匹配**；
- 前端：树形工作台 + Vditor 编辑器；
- 历史：Cognee 记忆系统（外部图引擎 + 嵌入 + LLM 管线）因可靠性问题已于 REQ-57 整体下线。

核心差距（相对"完备的 LLM Wiki"）：

| # | 差距 | 后果 |
|---|---|---|
| 1 | 检索只能字面匹配 | 换个同义词就搜不到；agent 找上下文靠猜关键词 |
| 2 | 文档之间没有内链体系 | 引用只有实体级 ref，正文里无法 `[[链接]]` 到别的 Wiki/词条，知识不成网 |
| 3 | 无机器可读的元数据规范 | 没有 summary/tags/owner/复核日期，LLM 无法快速判断"这篇讲什么、还新鲜吗" |
| 4 | 无上下文组装能力 | agent 要自己一篇篇翻文档拼上下文，token 浪费大且容易漏 |
| 5 | 无导出面 | 外部工具/网站无法按约定抓取全库知识（llms.txt 等） |
| 6 | 创作溯源不显性 | created_by 有 UUID 但界面上看不出"agent 写的草稿"还是"人定的稿" |

## 2. 概念铺垫：语义检索是什么（已裁定不做，存档备查）

**现状（关键词检索）**：数据库拿你输入的字符串去逐字比对标题和正文。搜「部署」找不到只写
「上线发布」的文档；搜「登录失败」匹配不到写着「认证错误」的段落。它只认**字面**。

**语义检索（向量检索）**：把每段文本交给一个"嵌入模型"（embedding model），转换成一个高维
数字向量（比如 1024 个数），这个向量可以理解为这段话**意思的坐标**——意思越接近的两段话，
坐标距离越近。

**用户裁定（2026-10-07）**：不采用语义检索。理由：不可靠且会引入大量不相关文档；关键词检索
最好，LLM 自己挑选和使用的关键词比语义召回更精确。本设计 v2 起全部检索走纯关键词路线。

## 3. 能力分层模型

```
L4 协作层   溯源标识 · 过期检测 · 质量信号（人机共创治理）
L3 组装层   wiki.context 上下文打包（待 D7 裁定）· llms.txt / Markdown 导出
L2 检索层   纯关键词检索（pg_trgm 多词子串 + 相似度排序）· 命中片段召回
L1 结构层   frontmatter 元数据 · [[双链]]与反链 · 术语自动链接 · 模板
─────────────────────────────────────────────
现有地基    wiki 树 + glossary + 版本 + 实体引用 + 评论 + 附件（全部保留）
```

### L1 结构层（无论如何都建议做，无外部依赖）

1. **frontmatter 元数据规范**：文档正文顶部可选 YAML 块：
   ```yaml
   ---
   summary: 一句话摘要（agent 检索预览用）
   tags: [deploy, tls]
   owners: [alice]          # 责任人
   review_date: 2026-12-01  # 复核期限
   doc_kind: howto          # spec / adr / howto / reference / note
   aliases: [部署手册]       # 检索别名
   ---
   ```
   解析进 `doc_metadata`（现有 JSON 列，无需迁移）；`get/list` 接口返回结构化字段；
   搜索结果带 summary 而不是截断正文。
2. **`[[双链]]` 与反链**：正文支持 `[[DOC-12]]`、`[[TERM-3]]`、`[[标题]]`（项目内按标题解析）、
   `[[标题|显示文本]]`、`[[标题#小节]]`（变体集对齐 Obsidian,survey C3;`#^` 块引用为 Obsidian
   私有,不进一期）。解析结果落 `doc_links` 表（from_doc, to_doc, anchor 文本;解析失败保留断链行
   ——to_document 置 NULL、to_text 记原文,点击可创建目标文档,Obsidian 模式）；文档详情返回反向
   链接列表；前端正文渲染成跳转链接。删除/改名时给出断链提示（不阻塞）。标题与 aliases 避开
   `# | ^ :` 等链接非法字符；aliases 必须 YAML list、tags 建议 list（Obsidian/Jekyll 惯例）。
3. **术语自动链接**：渲染层把正文中与 glossary 词条标题/aliases 匹配的词自动标出（不改动
   原文），人读时获得悬浮释义，agent 读时通过导出面拿到术语表。
4. **模板**：`doc_kind` 对应的骨架模板（创建时可选），存为系统级 Wiki（每项目初始化或全局只读）。

### L2 检索层（纯关键词增强，2026-10-07 已裁定不做向量）

目标：保持「子串匹配」语义（LLM 挑关键词 → 精确命中的心智模型），把执行层面做对：快、
可排序、可过滤。**不引入分块表**——纯关键词检索无需 chunk 结构，直接对整篇文档建索引，
命中后用 `similarity`/位置信息返回相关片段。

1. **索引**：`CREATE EXTENSION pg_trgm`（自带 contrib，零镜像变更）；对
   `document.title`、`document.content` 建 GIN trigram 索引（`gin_trgm_ops`）；
   requirement/task 两域同样处理。
2. **查询语义**：
   - 单关键词：等价现在的 `%kw%` ILIKE（行为兼容），但走索引而非全表扫描；
   - 多关键词（空格分隔）：逐词子串匹配（LLM 一次给多个候选词时不必多次调用），
     默认 OR 语义，结果标注每篇命中了哪些词；
   - 排序：trigram 相似度为主（`similarity(title, kw)` 加权 > content 相似度），
     `updated_at` 新鲜度作次级排序；替换现在的「纯按更新时间」。
   - 实施注记（survey C1,PG 官方文档核实）：GIN 只做候选过滤,**相似度排序在服务端对候选集
     计算**（"ORDER BY dist … can be implemented quite efficiently by GiST indexes, but not
     by GIN indexes";61 篇候选集小无压力,届时 top-K 若成瓶颈再评估 GiST）;<2–3 字符关键词
     （尤其中文）走兜底——别名/DOC-n 短码精确匹配或普通 LIKE（"a pattern with no extractable
     trigrams will degenerate to a full-index-scan"）;**CJK trigram 行为官方文档未覆盖,
     上线前用真实中文语料 EXPLAIN 实测**,勿假设按字切分。
3. **片段返回**：命中后基于词位置截取上下文片段（替代现在的「前 300 字硬截断」），
   每篇返回 1–3 个命中片段。
4. **结构化过滤**：module（wiki/glossary）、doc_kind、tags（依赖 L1 frontmatter）；
   glossary 词条的 aliases 参与匹配。
5. **接口**：`search.query` 升级（多词、片段、过滤）；新增 `docs.search`（文档专用）。
   错误与分页语义保持现有四件套约定。

### L3 组装层

1. **`wiki.context` 上下文打包**（待 D7 裁定，见 §5.6）：输入：主题/问题 + 预算（如 8000 token）+ 可选锚点文档。
   逻辑：混合检索取候选块 → 图扩展（锚点的双链邻居、引用的关联实体文档加权）→ 按相关度
   装配（每文档取「路径行 + frontmatter + 最相关块」）→ 预算内截断并输出清单（读了什么、
   还有什么没装下）。输出直接可喂 LLM。这是给 agent 的核心武器：一次调用拿到结构化上下文包。
2. **导出面**：`/api/projects/{id}/wiki/llms.txt`（按 llms.txt v2 规范,survey A1/A3：H1 +
   blockquote 摘要（复用 summary）+ H2 分节、每条为指向 .md 版的链接+一句话备注;单索引超
   ~100k 字符时按 Mintlify `/_llms/` 模式递归拆分,61 篇暂用不到;llms-full.txt 非规范义务,
   可后置）与 `…/export.md`（单篇或全库 Markdown 拼接）；经 nginx 暴露给外部工具。
   MCP 暴露形态（survey C2,规范原文核实）：文档本体用 resource template
   （如 `zeichen://docs/{id}`,只读被动数据,官方示例恰含 "Access knowledge bases"）;
   搜索/反链查询/（若裁定做的）wiki.context 用 tool——「服务端预组装」在 MCP 无原语对应,
   实现为 tool 返回组装片段 + resource links,不伪装成 resource。DSH 插件二期把 `docs.search`
   （及裁定后的 `wiki.context`）暴露为原生工具。

### L4 协作层

1. **溯源**：文档与版本详情标注创作主体（人名 / agent 名 + 其主人）；agent 批量产出建议
   打 metadata.provenance。
2. **过期检测**：`review_date` 到期 → 列表标黄；文档 derives 的需求已取消/完成 → 详情页提示
   「依据已变化」；给出一键「申请复核」评论动作。
3. **质量信号（二期）**：断链数、无摘要、超长未复核等清单页（「Wiki 体检报告」）。

## 4. 数据模型变更草案（v2：纯关键词版）

```sql
-- pg_trgm 扩展（自带 contrib，不换镜像）
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_document_title_trgm ON document USING gin (title gin_trgm_ops);
CREATE INDEX idx_document_content_trgm ON document USING gin (content gin_trgm_ops);

-- 新表：文档双链（L1，待 D5 裁定后实施）
CREATE TABLE doc_link (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  from_document_id VARCHAR(16) NOT NULL,
  to_document_id VARCHAR(16) NOT NULL,        -- 解析失败时 NULL + to_text 记原文
  to_text VARCHAR(256),
  anchor VARCHAR(256),
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (project_id, from_document_id, to_text)
);
```

- 无 chunk 表、无向量列、无 tsvector 列（v2 依据 D1–D3 裁定移除）；
- `Document` 表不改列（frontmatter 进现有 `doc_metadata`）；
- 双链若采用「写入时落表」：版本回滚 → 重建该文档 doc_links；worker 保留断链扫描任务；
- glossary 词条参与同一套检索（与 wiki 同表同索引）。

## 5. 技术决策点（D1–D6 与附件已裁定；D7 讨论中）

D1（嵌入模型）、D2（向量存储）、D3（分词/索引）已于 2026-10-07 裁定：**不做向量，纯关键词，
pg_trgm 索引**；D4（摘要：创作时写）、D5（双链：做、写入时落表）、D6（一期范围）同日裁定，
附件检索裁定**不进**（详见文首「决策进展」）。以下 D7 议题详细展开，**不设倾向、不预设
结论**，写清现状、机制、代价与后果，供独立判断；D4/D5 展开材料保留存档备查。

### 5.4 D4 摘要来源（已裁定 2026-10-07：B 创作时写；材料存档备查）

**现状（生产实测）**：搜索结果里的 `summary` 字段 = 正文前 300 字符硬截断（`content[:300]`）；
不是任何意义上的"摘要"。61 篇 wiki 的 metadata 使用率为 0；后端零 LLM 依赖（REQ-57 之后）。

**摘要在本设计里的用途**（为什么会有这个议题）：① 搜索结果预览——LLM/人不打开文档就能判断
相关性；② `wiki.context` 上下文打包——每篇的头部信息，预算内能装更多篇；③ llms.txt 导出
索引——目录页每行一条。**它只影响预览与打包效率，不影响检索召回本身。**

| 选项 | 机制 | 得到 | 代价/后果 |
|---|---|---|---|
| A 不做 | 维持前 300 字截断 | 零成本零纪律 | 前 300 字常是标题重复/状态行/前言，预览信息密度看运气；若你认为 LLM 反正会打开全文，则预览无关紧要 |
| B 创作时写 | 保存者（agent/人）在 frontmatter 写 `summary:`；后端只解析与返回，缺省回退截断 | 零后端 LLM 依赖；agent 写文档时顺手生成一句（agent 本身就是 LLM）；可在 Skills 里定为纪律 | 覆盖率靠纪律：存量 61 篇无 summary（回退截断或一次性补写）；summary 与正文可能脱节（改了正文忘改 summary，无机制强制同步） |
| C 后端自动生成 | 保存/更新时后端调 LLM API 生成并存储 | 全自动 100% 覆盖（含存量） | 后端重新引入 LLM 凭据/配置/失败处理（REQ-57 刚移除这类依赖）；保存延迟或异步任务；持续 token 费用；与「智能都在 agent 侧、后端保持纯 CRUD」的既有方向相悖 |
| D 机械提取 | 读取时按规则提取（如一级标题下第一段） | 零依赖零纪律，比截断稍好 | 仍是原文片段而非凝练摘要；规则对文档结构不稳定 |

### 5.5 D5 双链时机（已裁定 2026-10-07：做，A 写入时落表；材料存档备查）

**现状（生产实测）**：正文 0 处 `[[…]]`——今天文档之间没有任何正文内链接机制；想指路只能写
纯文本标题。跨实体关联已有一套独立机制：Reference 表 + `ref.create/ref.list` API（derives/
documents/implements/mentions），由**显式工具调用**建立，与正文内容无关。

**先决问题——要不要做正文双链（选项 0 = 不做）**：不做则互链继续走 ref API（显式、结构化，
但 LLM 写文档要多调一次工具，且正文里读者点不到）；做则 `[[DOC-12]]`/`[[部署手册]]` 直接成链。
**关键事实**：文档短码 DOC-n/TERM-n 是稳定主键（永不改变、不可复用），按短码链接不会因改名
断链；项目内标题唯一约束已存在（`_assert_document_title_unique`），按标题解析也是确定的。

若做，两种实现时机：

| 维度 | A 写入时落表（doc_link 表） | B 读取时解析（不落表） |
|---|---|---|
| 机制 | create/update/rollback 时后端解析正文全部 `[[…]]`，解析目标后落表 | 每次展示详情时现场解析渲染 |
| 正向链接展示 | 查表渲染，成本可忽略 | 现场解析，成本可忽略 |
| **反链查询**（"哪些文档链到我"） | 一条索引 SQL，即时 | **致命伤**：需把项目全部文档正文拉出逐篇正则，无法建索引；61 篇尚可，几百篇即每次全扫 |
| wiki.context 图扩展（沿链接找相关文档） | 直接查表，可扩展 | 每次组装全量扫描，实际不可用 |
| 保存时断链警告 | 可即时返回（"链接目标不存在/已删"） | 不可能 |
| 写入路径 | 稍重（毫秒级解析+写表）；软删目标时链接行保留并标断链 | 完全不动 |
| 新增要定的规则 | 按标题解析重名处理（现有唯一约束已消解）；软删目标的表现 | 无 |
| 存量迁移 | 61 篇无 `[[`，零回填，表从空开始 | 无 |

交叉事实：如果后续要 `wiki.context` 做「沿链接扩展」，A 是唯一可扩展形态；如果只想要正文
可点、不要反链与图扩展，B 够用。

### 5.6 D7 wiki.context：做不做、做多远（讨论中，三选一）

**背景**：wiki.context = 服务端单次接口，多关键词检索 → 沿双链/引用扩展 → 段落级摘取 →
token 预算内组装返回，替代 agent「搜 → 拉全文 → 翻找 → 再搜」的多轮往返。

**现状（生产实测）**：agent 现取上下文即上述多轮路径——每轮拉回整篇文档（平均 3977 字、
最长 42215 字），token 开销大且容易漏；`search.query` 为整串 ILIKE 子串匹配、按 updated_at
排序、预览为前 300 字硬截断。

**关键转折**：用户研读 Cline 文章（§9）后，此议题从「单项目 vs 跨项目」扩展为「做不做」。
Cline 哲学（agentic search：agent 自己带工具探索，反对服务端预组装）对 wiki.context 构成
直接挑战——其支付函数例子正是「组装逻辑漏掉没写关键词的自建框架」。该立场与 D1 裁定
（LLM 自己挑的关键词比语义召回更精确）同源：判断力放在 agent 侧，后端只提供锋利的原子工具。

| 路线 | 内容 | 特征 |
|---|---|---|
| 甲（Cline 式探索面） | 不做组装接口；磨利探索工具：`docs.wiki.get` 返回**双链+反链**（agent 顺着跟，等同 Cline 跟 import）、`search.query`/`docs.search` 多关键词、文档树/llms.txt 索引 | agent 自判相关性；几乎全是 W1/W2 副产品，成本低 |
| 乙（做+单项目） | wiki.context 在单项目内组装；跨项目找线索先 `search.query`（本就跨项目）再切项目 | 边界清晰、链扩展完整 |
| 丙（做+跨项目） | 一次跨所有有权限项目组装 | 需标注来源项目+去重规则，链扩展跨项目部分失效（双链只在项目内解析） |

**诚实评估**（已向用户申明）：61 篇语料下组装接口「合理但非必需」，分界线在几百篇；W3 排
最后，现在砍掉等文档多了再立项也完全合理。**无论选哪条，W1/W2/D5 都照做**（两条路线都吃
双链表与关键词检索）。若选甲，W3 改写为「探索面强化 + llms.txt 导出」。

**调查证据（2026-10-07 三路一手调查,详见 [llm-wiki-survey-20261007.md](llm-wiki-survey-20261007.md),
以下为证据陈述、非建议）**：

- **甲/乙在证据与 MCP 语义下不互斥**：Mintlify Index 的 context 端点（按 token 预算组装、
  带出处）与 search/contents 探索原语在同一产品并存；wiki.context 在 MCP 里天然是「多一个
  tool」,W1/W2 探索工具任何路线都照做——D7 的真问题从「做不做」收敛为**「现在做,还是等
  语料大了再做」（时机问题）**。
- **Cline 三论（切块毁逻辑/索引腐烂/安全面翻倍）移植到本项目基本不成立**：pg_trgm 不切块、
  组装摘「段落」且可带链接溯源;61 篇索引重建秒级;关键词索引不出域。其打击对象「向量 RAG +
  云端嵌入」已随 D1 裁定消失。
- **组装方的官方一手依据**：Claude Code 官方把 "The infinite exploration"（读几百个文件
  填满上下文）列为失败模式,官方修复 = 收窄范围 + 子代理摘要;Anthropic 承认 "runtime
  exploration is slower than retrieving pre-computed data"、会 "chasing dead-ends",且
  hybrid 策略官方认为适合 "less dynamic content, such as legal or finance"——项目 wiki
  属弱变更内容。
- **规模前提双向都不满足**：Cursor 检索增益实测集中 ≥1000 文件（61 篇远低于此,反向支持
  D1 纯关键词）;同理 Anthropic「预取」的价值也在大语料才显著——「61 篇下合理但非必需,
  分界线在几百篇」的评估经调查**维持不变**。
- 诚实边界：所有一手来源均来自代码 agent 产品与文档产品,无一与「61 篇项目 wiki + agent
  消费」同构,移植为推断;pg_trgm 的 CJK 行为须实测。

## 6. 分期（v3；W3 内容待 D7 裁定后定稿）

```
W1  L1 结构层：frontmatter 规范与解析（含 summary，D4-B）、[[双链]]写入时落表（D5-A）、
    术语自动链接、模板
W2  L2 检索层：pg_trgm 扩展与索引、多词子串检索、相似度排序、命中片段、docs.search
W3  L3 组装层（待 D7）：乙/丙 = wiki.context 打包；甲 = 探索面强化（docs.wiki.get 返回
    双链+反链）；两者均含 llms.txt / export.md 导出、DSH 插件暴露 docs.search（乙/丙另暴露 context）
W4  L4 协作层（一期内，随依赖排布）：溯源标识（无前置，可随 W1）＋
    过期检测（review_date 到期标黄 + derives 依据需求取消/完成时提示，排 W1 之后）
    ——体检报告已裁定不做（D6）
```

依赖关系：W1、W2 可并行；溯源无前置可先行；过期检测排 W1 后；W3 依赖 W1 + W2；
计划一的 M2/M3（插件工具）与 W3 的插件暴露衔接。

## 7. 与 Cognee 下线（REQ-57）的边界

- 不恢复 Cognee、不引入外部图引擎/记忆产品；
- 不做向量/嵌入（D1 裁定），后端不引入任何模型推理；
- 若 D4 裁定为「创作时写」，后端继续保持零 LLM 依赖。

## 8. 开放问题

1. ~~glossary 是否参与向量检索~~——随 D1 取消（无向量检索）；glossary 与 wiki 同表同索引参与关键词检索（§3 L2 已含）。
2. ~~附件是否进检索~~——已裁定**不进**（2026-10-07，见文首决策表）。
3. ~~wiki.context 是否限定单项目~~——并入 D7 三路线议题（§5.6）。
4. W4 质量信号是否需要新的权限角色（如「文档管理员」），还是沿用现有项目角色（建议：沿用）？——体检报告已随 D6 不做，此题降为二期议题。

## 9. 关键参考（讨论中已核实原文）

- [Cline: Why Cline Doesn't Index Your Codebase](https://cline.ghost.io/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing/)——三个反 RAG 论点（切块撕碎逻辑/索引腐烂/安全面翻倍）、「像开发者一样探索」、支付错误处理对照例；与用户检索裁定（D1）完全同向。官方站 [cline.bot](https://cline.bot/blog/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing) 正文需 JS，用 Ghost 镜像。
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)——「最小高信号 token 集」原则；子代理「大量探索→只返回 1–2k token 蒸馏结果」（wiki.context 的模式出处）；也点明预组装的代价（慢于预计算、组装逻辑漏了就是漏了）。
- [Cognition: DeepWiki](https://cognition.com/blog/deepwiki)——「给 LLM 吃的 wiki」产品形态实证（5 万+仓库）。
- [AnswerDotAI/llms-txt](https://github.com/AnswerDotAI/llms-txt)——llms.txt 标准（W3 导出面依据）。
- 诚实边界（已向用户申明）：实证的是**零件**（子代理压缩/agentic 关键词搜索/LLM 知识层），wiki.context 的具体接口形态是按本项目约束的组合，非照抄某产品。
- **2026-10-07 一手资料调查汇总**：[llm-wiki-survey-20261007.md](llm-wiki-survey-20261007.md)——新增一手来源：llms.txt v2 规范、Mintlify llms.txt/Index API、DeepWiki/Devin 官方文档、Cursor semsearch 与 secure-codebase-indexing 研究博客、Claude Code best practices、Sourcegraph Cody 文档、MCP 规范 2026-07-28、PostgreSQL pg_trgm 官方文档、Obsidian 官方帮助、Jekyll frontmatter 文档;含 D7 证据地图与两处技术假设修正（GIN 不加速排序、短中文词兜底）。
