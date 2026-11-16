# Survey:LLM Wiki 设计一手资料调查(2026-10-07)

> 目的:为计划二「LLM Wiki 系统改造」设计稿定稿补充证据,重点服务待决议题 D7
> (wiki.context 组装接口 vs 探索面工具)与 W1/W2/W3 分期。
> 方法:三路并行调查——A 产品与格式、B 检索哲学、C 构建块核实。只收一手来源
> (规范原文、官方博客、官方文档、官方仓库),全部经 web_fetch 拉全文核实,
> 关键论点附原文短引;二手资料不收,查不到的明确标注。
> 状态:**调查完成**(三路全部返回;A 关键结论经 Lead 抽查,Mintlify 端点家族由 Lead 复核)。

---

## A. 面向 LLM 的文档/知识库产品与格式

### A1. llms.txt 规范 v2(规范/官方仓库)

来源:[github.com/AnswerDotAI/llms-txt](https://github.com/AnswerDotAI/llms-txt)
(正文在 `nbs/index.qmd`,`README.md` 为指向它的符号链接)

- Jeremy Howard 2024-09-03 提出,2026-08-10 改版 v2;自述为非正式提案:
  "The llms.txt specification is open for community input."
- 采用现状(规范自述):"thousands of sites publish an llms.txt file… Chrome's
  Lighthouse audits sites for one as part of its agentic browsing checks."
- 格式:H1(唯一必填)→ blockquote 摘要 → 任意非标题说明段 → H2 分节文件列表,
  每条为 `[name](url): 备注`;Optional 节放次要链接。
- **核心机制是「小索引 + 按需取」**:"Agents are expected to view or search llms.txt
  to find the information they need, then follow the relevant links… The file itself
  stays small enough to fit in context."
- v2 新增:同 URL 提供 .md 干净版,经 `rel="alternate"`/`rel="describedby"`(Link 头)发现;
  文件可放任意子路径、覆盖其下页面。
- ⚠ **规范原文通篇未定义 llms-full.txt**(grep 证实)——它是平台事实约定,不是规范义务。

### A2. Anthropic 文档站实例(官方实例)

来源:docs.anthropic.com/llms.txt 重定向至
[platform.claude.com/llms.txt](https://platform.claude.com/llms.txt)(已验证存在)

- 形态完全合规:H1 + blockquote + H2 分节 + 带一句话描述的 .md 链接;
  按语言分节(英文 754 页、其余各 265 页);结尾附 llms-full.txt 指引。

### A3. Mintlify:llms.txt 自动生成(官方文档)

来源:[实例](https://www.mintlify.com/docs/llms.txt) +
[官方文档](https://www.mintlify.com/docs/ai/llmstxt)

- 默认全客户自动生成:"Mintlify automatically hosts an llms.txt file at the root of
  your project… always up to date and requires zero maintenance."
- **frontmatter 直接成为导出原料**:"Each page's description comes from the
  `description` field in its frontmatter. Mintlify uses the first paragraph of the
  description and truncates it at 300 characters."
- 规模化:单索引超 100,000 字符自动拆为 `/_llms/` 递归子索引
  ("Follow each `/_llms/` index recursively until you reach documentation pages");
  llms-full.txt 纳入 `for="agents"`、排除 `for="humans"` 的内容。

### A4. Mintlify Index API:组装与探索并存(官方文档)

来源:/docs/api/search-index/*(Context / Search / Contents 三端点;Lead 已抽查核实
「Build implementation context」页与三端点家族确实存在)

- context 端点:按 token 预算返回带出处引用的组装内容("ready-to-use context in
  one request" 语义);
- **同时**提供 search + contents 两步探索原语——组装接口与探索原语在同一个成熟产品里
  并存,不是二选一。

### A5. Cognition DeepWiki(官方博客 + 官方文档)

来源:[cognition.com/blog/deepwiki](https://cognition.com/blog/deepwiki)(2025-05-05)
+ docs.devin.ai 的 deepwiki / deepwiki-mcp 页

- "we're launching DeepWiki, the free public version of Devin Wiki and Devin Search";
  已索引 5 万+仓库;github.com 换 deepwiki.com 即访问。
- 组织方式前置在**生成期**:仓库根 `.devin/wiki.json` 显式列页
  (title/purpose/parent 层级,≤30 页)+ repo_notes,存在时绕过默认聚类规划。
- DeepWiki MCP(免费免鉴权远程 MCP)三工具:read_wiki_structure(列主题)/
  read_wiki_contents(读内容)/ ask_question(问答)——典型「探索面」形态。

### A6. Devin Knowledge 已弃用(官方文档)

来源:docs.devin.ai/onboard-devin/knowledge-onboarding

- "Knowledge is deprecated and will be removed in a future update. Existing Knowledge
  is being migrated to Skills in Plugins automatically."
- 仅自动导入特殊后缀文件(.mdc/.cursorrules/CLAUDE.md/AGENTS.md 等):
  "Devin won't automatically pull in more general file types like `.md`."

### A. 未查到/不确定

- OpenAI 的 llms.txt(developers.openai.com)本网络 curl 得 403、Gemini 返回空,
  无法直接验证(仅规范 v2 单方声称存在);
- ChatGPT / GitHub Copilot 官方文档中「如何向模型喂文档资源」的专门页面未找到。

### A 部分结论 → 对设计的启示

1. **[W3]** llms.txt 导出按 v2 规范做:H1 + blockquote(复用 summary)+ 按主题/tags
   H2 分组的 .md 链接;llms-full.txt 非规范义务、可后置;规模大时学 Mintlify
   `/_llms/` 递归拆分(100k 字符阈值,61 篇语料暂用不到)。
2. **[W1]** summary 是导出物料直接原料(Mintlify 取 description 首段、截 300 字符)
   → 应约束 summary「首段自含 + 限长」;tags 可作导出分节依据。
3. **[D7]** 一手证据整体偏「探索面」(规范 = 小索引 + agent 跟链;DeepWiki MCP =
   结构→内容→问答三工具),但 Mintlify Index 证明「token 预算内一次组装」有真实
   需求——若做 wiki.context,应返回带出处引用,且与 search/read 原语**并存**而非互斥。
4. **[D7]** DeepWiki 把组织成本前置在生成期(wiki.json 舵控页面结构),不在查询期组装;
   Zeichen 的 [[双链]]/反链落表天然提供结构化导航面,喂给探索工具即可。
5. **[W1]** Devin Knowledge 弃用、迁移到按触发检索的 Skills,提示「静态全量知识条目」
   价值衰减;frontmatter 可预留 trigger/audience 类字段,让文档按场景被检索命中
   (是否加字段待用户裁定,先记录)。

---

## B. 检索哲学:agentic search vs 预计算索引

### B1. Cline 官方博客(反索引方)

来源:[cline.ghost.io/why-cline-doesnt-index-your-codebase…](https://cline.ghost.io/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing/)(2025-05-26)

- 切块毁逻辑:"when you chunk code for embeddings, you're literally tearing apart its
  logic"(函数调用在 chunk 47、定义在 892);
- 索引腐烂:"An index, by definition, is a snapshot frozen in time"、"Every merge is
  a potential divergence";
- 安全面:嵌入是 IP 的第二副本,"you've just doubled your security surface";
- 探索式替代:像高级工程师一样 "systematic exploration","building context by
  following the natural structure of your code";
- 支付函数例:RAG 检 "payment/error" 会 "miss the custom error handling framework
  your team built",Cline 则沿 imports 追到错误处理工具并读调用方;
- 承认:"Yes, RAG can save tokens."

### B2. Anthropic 工程博客(探索方,但承认代价、官方推荐混合)

来源:[anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)(2025-09-29)

- 最小高信号集:"finding the smallest possible set of high-signal tokens that
  maximize the likelihood of some desired outcome";
- **「agentic search」一词的一手出处即此文**(小节 "Context retrieval and agentic
  search"):agent 持轻量标识符(文件路径/链接)"dynamically load data into context
  at runtime";Claude Code 用 "glob and grep… effectively bypassing the issues of
  stale indexing and complex syntax trees";
- 子代理蒸馏:"Each subagent might explore extensively, using tens of thousands of
  tokens or more, but returns only a condensed, distilled summary (often 1,000-2,000
  tokens)";
- 预组装代价(官方同时承认):"runtime exploration is slower than retrieving
  pre-computed data"、agent 可能 "chasing dead-ends";
- 官方推荐混合:CLAUDE.md 预入上下文 + grep/glob 现场探索,"The hybrid strategy
  might be better suited for contexts with less dynamic content, such as legal or
  finance work";"do the simplest thing that works"。

### B3. Claude Code 官方 best practices(无界探索 = 官方列名的失败模式)

来源:code.claude.com/docs/en/best-practices(原 anthropic.com/engineering/
claude-code-best-practices 已重定向改版,原 grep/glob 段落已删,以下为 2026 新版等价内容)

- "The infinite exploration" 列为官方失败模式:"Claude reads hundreds of files,
  filling the context",修复 = "Scope investigations narrowly or use subagents";
- "Since context is your fundamental constraint, use subagents to keep research out
  of it",子代理 "report back summaries"。

### B4. Cursor 官方研究博客(索引方,带实测数字)

来源:[cursor.com/en-US/blog/semsearch](https://cursor.com/en-US/blog/semsearch)(2025-11-06)、
[prod.cursor.com/cn/blog/secure-codebase-indexing](https://prod.cursor.com/cn/blog/secure-codebase-indexing)(2026-01-27)

- 自训 embedding + 索引管线,"semantic search significantly improves agent
  performance, especially over large codebases":问答准确率平均 +12.5%(6.5–23.5%),
  A/B 中代码留存率在 **≥1000 文件库** +2.6%,无语义搜索时用户不满跟进 +2.2%;
- "Semantic search is currently necessary to achieve the best results, especially in
  large codebases";但 "the combination of these two (grep+semantic) leads to the
  best outcomes";
- 对抗索引腐烂的基建:Merkle 树增量同步 + 块级 embedding 缓存 + simhash 复用队友索引
  (5 万文件库首次查询 4.03h→21s)——腐烂/成本是真实问题,但被基建压制而非否认;
- 注:官方 docs 的 codebase-indexing 旧页(docs.cursor.com)已重定向至
  cursor.com/docs/agent/tools/search,旧页原文不可得;新文档主打本地 Instant Grep
  ("a custom search engine that outperforms ripgrep"),grep 索引声明 "on your machine"。

### B5. Sourcegraph Cody 官方文档(混合方)

来源:docs.sourcegraph.com/cody/core-concepts(正文经 5.7 版存档 + GitHub docs 仓库 raw 核实)

- 官方检索 = 四路混合:Keyword Search、Embeddings、Sourcegraph Search、Code Graph,
  "All these methods collectively ensure… high-quality context";
- Keyword Search "comes out of the box without any additional setup… a
  cost-effective and time-saving solution";
- 且关键词检索也建本地索引:"Cody uses symf, a local keyword search engine, to
  create and maintain code indexes… Detects file changes and reindexes as needed"。

### B6. OpenAI Codex CLI(无索引,沉默)

来源:[github.com/openai/codex](https://github.com/openai/codex)

- README 仅称 "a coding agent from OpenAI that runs locally on your computer";
  仓库 docs/ 全部 15 个文件经 grep 核查无任何 index/embedding/retrieval/semantic
  search 内容——无索引,官方也未解释检索方式(注:developers.openai.com/codex 返回
  403,网页版文档无法核验)。

### B. 分歧地图

| 争点 | 反索引方(Cline/Anthropic) | 索引方(Cursor/Sourcegraph) | 各自前提 |
|---|---|---|---|
| chunk vs 整篇沿链 | 切块 "tearing apart logic" | AST 感知切块+缓存,实测有收益 | 语料规模(Cursor 收益集中 ≥1000 文件)与切块质量 |
| 预计算 vs 现场探索 | "bypassing stale indexing" | 腐烂用 Merkle/增量同步压制 | 代码(强链接、高频变更)vs 文档(弱变更) |
| 关键词 vs 语义 | Cline 反的是「向量嵌入」而非关键词;Anthropic 用 grep/glob | Cursor:混合最好;Sourcegraph:四路混合 | Zeichen 裁定 pg_trgm 后,真争点只剩「谁来组装」 |
| 安全 | 嵌入上传=IP 第二副本 | 本地/私有部署 | Cline 论点只对「上传嵌入到云端」成立;本地 pg_trgm 无此面 |

### B 部分结论 → 对 D7 的启示(61 篇 wiki、消费方是 agent)

1. **Cline 反索引三论移植到 Zeichen 后基本不成立**:①pg_trgm 不切块,wiki.context
   摘「段落」而非向量 chunk,且可带链接溯源,撕碎逻辑问题弱化;②61 篇规模索引重建
   秒级、腐烂可全量重建,无需 Merkle 级基建;③关键词索引不出域,无嵌入外泄面。
2. **Cursor「语义收益集中在大库」的前提在 61 篇不满足**:纯关键词召回在此规模够用
   ——支持已做的 D1 裁定。
3. **Anthropic 双向都支持**:子代理蒸馏模式(大量探索→1000-2000 token 摘要)正是
   wiki.context 的服务端版;但其 "runtime exploration is slower" 与 "chasing
   dead-ends" 也警告纯 agentic 路线多轮往返贵、会走死胡同。
4. **Claude Code 官方把 "infinite exploration" 列为失败模式,修复 = "narrow scope +
   subagent 摘要"**——为一次性组装接口提供了正面依据:服务端 wiki.context(检索→
   沿链扩展→段落摘取→预算拼包)≈ Anthropic 混合策略中「CLAUDE.md 预入上下文」角色
   的放大版,省掉 agent 的多轮探索税;agentic 路线可留作兜底(疑难时 agent 再多轮
   追问文档链接)。
5. B 路查不到的:Cursor codebase-indexing 旧文档页原文(已下线重定向);
   developers.openai.com/codex(403);Claude Code best practices 原版 grep/glob 段
   (重定向后删除,以 effective-context-engineering 文中 glob/grep 表述为官方替代证据)。

---

## C. 构建块一手核实:pg_trgm / MCP / Obsidian 双链 / frontmatter

### C1. PostgreSQL pg_trgm(官方文档,PG current/18)

来源:[postgresql.org/docs/current/pgtrgm.html](https://www.postgresql.org/docs/current/pgtrgm.html)

- **GIN 加速 ILIKE/子串:证实**。"these index types also support trigram-based index
  searches for `LIKE`, `ILIKE`, `~`, `~*` and `=` queries";"Unlike B-tree based
  searches, the search string need not be left-anchored."
- similarity/word_similarity 语义:证实。similarity 值域 "zero (completely dissimilar)
  to one (identical)";word_similarity = "the greatest similarity between the set of
  trigrams in the first string and any continuous extent of an ordered set of
  trigrams in the second string";strict_word_similarity 强制词边界。
- **GIN vs GiST【假设被修正】**:文档明确 "ORDER BY dist LIMIT 10 … can be implemented
  quite efficiently by GiST indexes, but not by GIN indexes"——**GIN 只做候选过滤,
  相似度排序需服务端对候选集计算**(61 篇规模无压力;若要 top-K 索引加速需 GiST)。
- **短词/子串限制【假设被修正】**:"The more trigrams in the search string, the more
  effective the index search is";"a pattern with no extractable trigrams will
  degenerate to a full-index-scan"。trigram 概念:每词前补两空格后补一空格
  ("cat"→"  c"," ca","cat","at "),故 1–2 字符词 trigram 极少、选择性差。
- **中文/CJK 行为官方文档未覆盖**(是否按字成 trigram 取决于实现与 locale)——
  上线前须用真实中文语料 EXPLAIN 实测,勿假设。

### C2. MCP 规范(2026-07-28 版)

来源:modelcontextprotocol.io/specification/2026-07-28(server/resources、server/tools)
+ 官方 learn/server-concepts

- Resources vs Tools 官方定义:Resources "designed to be **application-driven**, with
  host applications determining how to incorporate context";Tools "designed to be
  **model-controlled**, meaning the language model can discover and invoke tools
  automatically"。
- server-concepts 对比表:Resources = "Passive data sources that provide read-only
  access to information for context",**官方示例恰含 "Retrieve documents / Access
  knowledge bases"**;Tools = "Functions that your LLM can actively call"。
- Resource Templates:"allow servers to expose parameterized resources using URI
  templates",支持补全/分页。
- 工具可回链资源:"A tool **MAY** return links to Resources, to provide additional
  context or data."(Resource Links)。
- **「服务端预组装上下文」在 MCP 无对应原语**——若做,实现为 tool(输入查询意图,
  输出组装片段+resource links),不要伪装成 resource。

### C3. Obsidian 双链(官方帮助,正文取自官方仓库 obsidianmd/obsidian-help)

来源:help.obsidian.md(Internal links / Backlinks / Graph view / Aliases 页)

- 语法变体(证实):`[[Three laws of motion]]`、显示文本 `[[Example|Custom name]]`、
  标题 `[[About Obsidian#Links are first-class citizens]]`(可多级 #)、块引用
  `[[2023-01-01#^37066d]]`(官方明示 "Block references are specific to Obsidian and
  not part of the standard Markdown format")、路径 `[[Projects/Three laws of
  motion]]`、嵌入加 `!`。无效字符:"A string which contains the following characters
  may not work as a link: `# | ^ : %% [[ ]]`"。
- 反链面板两区:"**Linked mentions** are backlinks to the notes that contain an
  internal link to the active note";"**Unlinked mentions** are backlinks to any
  unlinked occurrence of the name of the active note"(按笔记名/别名全文匹配)。
- 断链:行为有据、术语未覆盖(官方帮助无 "unresolved links" 专页):"If the link
  points to a note that doesn't exist yet, Obsidian creates the note at that folder
  path";Graph view "Since a note doesn't need to exist to link to it…"(断链默认是
  图中节点,可过滤 Existing files only)。
- aliases(与 frontmatter 对齐):官方要求 "Aliases should always be formatted as a
  list in YAML",链接时展开为 `[[Artificial Intelligence|AI]]` 显示文本。

### C4. Jekyll Front Matter(官方文档)

来源:[jekyllrb.com/docs/front-matter/](https://jekyllrb.com/docs/front-matter/)

- 惯例证实:"The front matter must be the first thing in the file and must take the
  form of valid YAML set between triple-dashed lines."
- 自定义字段自由扩展:证实。"you can set predefined variables … or even create
  custom ones of your own."我们的 summary/tags/owners/review_date/doc_kind 无冲突。
- 警告:"make sure that no `BOM` header characters exist in your files"(UTF-8 BOM
  会让解析出问题——中文语料的实现细节)。

### C5. MediaWiki Help:Links(可选)

www.mediawiki.org 两次抓取超时,未查到,不引用。

### C 落地修正(已归一到本文 W 编号:W1 结构层 / W2 检索层 / W3 组装导出层)

1. **[W2]** 保持 GIN(gin_trgm_ops)做 ILIKE/LIKE 候选过滤;相似度排序在服务端对
   候选集计算(GIN 无法索引加速 ORDER BY distance;61 篇候选集小,无压力)。
2. **[W2]** <2–3 字符关键词(尤其中文)建立兜底:别名/DOC-n 短码精确匹配或普通
   LIKE 小表扫描;CJK trigram 行为官方未覆盖,**上线前用真实中文语料 EXPLAIN 实测**。
3. **[W1]** doc_link 落表保留断链行(to_document NULL + to_text 记原文)+ 点击创建
   目标文档(Obsidian 模式);解析器支持 `[[name]]`/`[[name|display]]`/
   `[[name#heading]]`;`#^` 块引用为 Obsidian 私有,不进首期;标题与别名约束避开
   `# | ^ :` 等字符;aliases 必须 YAML list,tags 建议 list。
4. **[W3]** MCP 暴露形态:文档本体用 resource template(如 `zeichen://docs/{id}`,
   只读);搜索/按 tag/反链查询用 tool(model-controlled);tool 返回值附 resource
   links 引导客户端继续读取;若做 wiki.context,实现为 tool 返回组装片段+resource
   links,不伪装成 resource。

---

## 综合结论:对 W1/W2/W3/D7 的证据地图

### D7(wiki.context 组装 vs 探索面)——三方证据

| 指向 | 一手证据 | 出处 |
|---|---|---|
| 探索面 | llms.txt 核心机制 = 小索引 + agent 跟链按需取 | A1 规范原文 |
| 探索面 | DeepWiki MCP = 结构→内容→问答三工具,无组装接口 | A5 官方文档 |
| 探索面 | "agentic search":agent 持轻量标识符按需加载,grep/glob 绕开陈旧索引 | B2 Anthropic |
| 组装 | Mintlify Index 的 context 端点(按 token 预算组装、带出处)与 search/contents **并存** | A4 官方 API |
| 组装 | "The infinite exploration" 列为**官方失败模式**,修复 = 收窄范围 + 子代理摘要 | B3 Claude Code |
| 组装 | 子代理蒸馏(大量探索→1–2k token 摘要)= 服务端组装的原型;"runtime exploration is slower"、会 "chasing dead-ends" | B2 Anthropic |
| 组装 | hybrid 适合 "less dynamic content, such as legal or finance"——项目 wiki 正是弱变更内容 | B2 Anthropic |
| 并存 | grep+semantic 混合最好(Cursor);四路混合(Sourcegraph);Mintlify 双轨 | A4/B4/B5 |

### 三条综合判断(证据陈述,非建议)

1. **甲/乙在证据与 MCP 语义下都不互斥**:Mintlify 实践双轨并存;MCP 里 wiki.context
   天然实现为「多一个 tool」(C2),W1/W2 的探索工具(检索/双链/反链/resource)任何
   路线都照做。因此 D7 的真问题从「做不做」收敛为**「现在做,还是等语料大了再做」
   (时机问题)**。
2. **Cline 三论不移植**(B1→D7):pg_trgm 不切块、索引秒级重建、不出域——你此前因
   Cline 文章对 wiki.context 产生的疑虑,其打击对象是「向量 RAG + 云端嵌入」,该对象
   已随 D1 裁定消失。
3. **规模前提双向都不满足**:Cursor 的检索增益实测集中 ≥1000 文件(B4),61 篇远低于
   此——关键词召回够用(支持 D1);同理,Anthropic 混合策略中「预取」的价值也在大
   语料才显著。此前「61 篇下组装接口合理但非必需,分界线在几百篇」的诚实评估,
   经本轮调查**维持不变**。

### 诚实边界

- 全部一手来源来自代码 agent 产品(Cline/Cursor/Claude Code/Codex)与文档产品
  (llms.txt/Mintlify/DeepWiki/Devin),**无一与「61 篇项目 wiki + agent 消费」同构**;
  移植到 Zeichen 场景均为推断,上表已标注出处供独立判断。
- pg_trgm 的 CJK 行为官方文档未覆盖(C1),任何「中文检索效果」结论须以实测为准。
- Devin Knowledge 弃用、Devin 文档对 OpenAI 远程 MCP 的反向引用等未核验项见各节
  「未查到/不确定」标注。
