# LLM Wiki 架构调研与参考架构(2026-10-07)

> **定位**:回答两个问题——**如何搭建 LLM Wiki?需要哪些核心功能点?**
> 方法:拆解现有系统的架构(一手资料:官方规范/文档/博客/论文),按同一套维度提取功能点,
> 综合成参考架构,再映射到 Zeichen。**不做哲学争论**(那部分见
> [llm-wiki-survey-20261007.md](llm-wiki-survey-20261007.md) 的 D7 证据地图)。
> 状态:**定稿**(两路补充调查均已合入并复核;关键引文经 Lead 抽查 agentskills.io
> 规范页原文确认)。

---

## 1. 问题定义:LLM Wiki 与普通 Wiki 的差异

LLM Wiki = **LLM/agent 是第一类读者兼作者**的知识库(人不缺席,但机器读者的约束优先)。
机器读者与人类读者的根本差异,决定了每个架构决策:

| 人类读者 | LLM/agent 读者 | 架构后果 |
|---|---|---|
| 用眼睛浏览,滚动跳读 | 按 token 预算进货,超预算即失明 | 需要**渐进披露**:索引→摘要→全文,按需加载 |
| 记得住站点结构 | 每次会话从零开始 | 需要**稳定标识**与**机器可读元数据**做路标 |
| 点链接很自然 | 一次工具调用有延迟与 token 成本 | 链接要**结构化落库**(反链可查),不能只埋在渲染里 |
| 凭语感判断相关性 | 凭关键词与摘要判断 | 检索要**可预测**(字面匹配)且结果带**判断材料**(摘要/片段) |
| 信任权威排版 | 无法分辨新旧真伪 | 需要**信任信号**:溯源、日期、过期状态 |
| 手动整理 | 可以批量写入 | 写入通道必须对 agent 开放,且写入时保持结构(解析管线) |

一句话:**普通 wiki 优化「人找到并读懂」,LLM wiki 优化「模型在 token 预算内取到高信号上下文,且写回来时不破坏结构」。**

## 2. 参考系统架构拆解

> 每个系统按:知识单元/组织结构、生成与写入、分发与加载、检索与导航、维护 五维拆解。
> 来源全部一手,引文 verbatim。

### 2.1 llms.txt v2 + Mintlify(规范 + 规模化实现)【已核实,survey A1/A3】

- **知识单元**:整页 .md 干净版 + 一句话描述;组织:H1 + blockquote 摘要 + H2 分节链接表。
- **生成**:Mintlify 从 frontmatter `description` 自动生成("Each page's description comes
  from the `description` field in its frontmatter… truncates it at 300 characters"),
  零维护("always up to date and requires zero maintenance")。
- **分发**:渐进披露的教科书——小索引常驻("The file itself stays small enough to fit
  in context"),agent 按需跟链("Agents are expected to view or search llms.txt… then
  follow the relevant links")。规模化:>100k 字符递归拆 `/_llms/` 子索引。
- **检索**:无内建检索,靠索引+跟链;另有 Index API 三端点(search / contents /
  context——token 预算内组装)。
- **维护**:随部署自动更新。

### 2.2 Anthropic Agent Skills(官方工程博客 2025-10-16 + 开放标准 agentskills.io)【一手已核】

- **知识单元**:目录=技能,`SKILL.md`(YAML frontmatter: `name`+`description` 必填)
  + 附属文件(scripts/references)。
- **组织**:「渐进披露」三级——①启动时只预载全部技能的 name+description 进 system
  prompt;②判定相关才读入 SKILL.md 全文;③再按需读附属文件("Claude can choose to
  navigate and discover only as needed")。"the amount of context that can be bundled
  into a skill is effectively unbounded"。
- **写入**:人写为主;"Iterate with Claude… ask Claude to capture its successful
  approaches"——官方明确倡导让 agent 沉淀自己的经验回技能。
- **分发**:文件系统即接口(agent 用 read 工具);代码作为可执行工具不进上下文。
- **维护**:官方建议「从评估出发增量构建」("Start with evaluation")。
- **标准细节(agentskills.io/specification 全文)**:目录 = SKILL.md + 可选 scripts/
  (可执行)/ references/(文档)/ assets/(模板资源);必填 `name`(1–64 字符,小写/
  数字/连字符,与目录同名)、`description`(1–1024 字符);可选 license、compatibility
  (≤500 字符)、metadata(任意 KV)、allowed-tools(实验)。
- **量化 token 预算(渐进披露的官方数字)**:"Metadata (~100 tokens): The name and
  description fields are loaded at startup for all skills";正文建议 <5000 tokens、
  "Keep your main SKILL.md under 500 lines";文件引用相对路径、"Keep file references
  one level deep from SKILL.md";skills-ref validate 校验。版本更新机制:文档未覆盖。

### 2.3 Cognition DeepWiki(官方博客 + 官方文档)【survey A5;管线细节待补】

- **知识单元**:主题页(架构图+文档+源码链接锚点)。
- **组织**:生成期定死结构——仓库根 `.devin/wiki.json` 显式列页
  (title/purpose/parent,≤30 页),存在时绕过自动聚类。
- **分发**:MCP 三工具 read_wiki_structure / read_wiki_contents / ask_question——
  结构→内容→问答,本身就是渐进披露。
- **检索**:结构导航为主,ask_question 兜底。
- **生成管线(官方文档)**:索引仓库 → 默认聚类规划成页——"When a config file is
  present, we bypass the default cluster-based planning and create exactly the pages
  you specify";`.devin/wiki.json`:repo_notes[{content ≤10000 字符, author}] +
  pages[{title(项目内唯一), purpose, parent, page_notes}],title/purpose 必填,
  ≤30 页(企业 80)、总 notes ≤100;三档 effort;提交后 regenerate。
- URL 直达分发:github.com 换 deepwiki.com 即访问。

### 2.4 Obsidian(双链产品事实标准)【survey C3】

- **知识单元**:笔记;`[[wikilink]]` 变体集(name/name|display/name#heading)。
- **组织**:链接落库才有反链面板(Linked mentions)+ Unlinked mentions(按名/别名全文
  找未成链提及);aliases 强制 YAML list。
- **维护**:断链是图中一等节点("a note doesn't need to exist to link to it"),
  点击即创建——断链不是错误,是待办。

### 2.5 MCP 规范 2026-07-28(互操作层)【survey C2】

- Resources(application-driven,只读被动,官方示例即 "Access knowledge bases")/
  Resource Templates(参数化 URI)/ Tools(model-controlled);
  "A tool **MAY** return links to Resources"——工具结果回链资源,构成「检索→深读」闭环。

### 2.6 agent 记忆系统:Letta(MemGPT)/ Mem0 / Zep(Graphiti)【一手已核】

**Letta**(docs.letta.com/v1-sdk/memory/ 四页,自标 legacy):
- 知识单元:memory block(label/value/limit/read_only,**常驻上下文的字符段**);
  archival passage(content+tags,单条限 300 tokens)。
- 组织:块=标签化扁平段;archival=向量库+tag 过滤;官方分层选型:块 <50k chars/<20 个、
  文件 5MB/<100、archival 无限——"For smaller amounts of data, it is best to simply
  place everything into the context window with memory blocks."
- 写入:agent 用内置工具自改块("Agents autonomously organize information based on
  block labels"):memory_rethink/replace/insert + archival_memory_insert。
- 上下文:块 "always visible - no retrieval needed";archival/文件按需工具加载。
- 共享:块 attach 到多 agent,"update once, visible everywhere";并发 last-write-wins。

**Mem0**(arxiv 2504.19413 官方论文):
- 知识单元:抽取式「事实」(自然语言句+embedding+metadata);graph 变体=实体+有向标边。
- 写入:两阶段("the complete pipeline architecture consists of two phases: extraction
  and update")——更新期 LLM tool-call 四操作:"ADD for creation of new memories…;
  UPDATE…; DELETE for removal of memories contradicted by new information; and NOOP
  when the candidate fact requires no modification";graph 版冲突 "marking them as
  invalid rather than physically removing them to enable temporal reasoning"。
- 上下文:无常驻;应用调 search 自行注入:"Your app decides which returned memories
  to include in the prompt."

**Zep/Graphiti**(arxiv 2501.13956 官方论文 + getzep/graphiti README):
- 知识单元:episode(原始数据,"Episodes serve as a non-lossy data store")/entity
  (名称+摘要+向量)/relation 边(带时间元数据)/community(簇摘要)。
- 组织:三层子图:episode → semantic entity → community(label propagation 动态扩簇)。
- 写入:全自动 LLM 管线(实体抽取→消歧→事实/时间抽取→Cypher 入图)。
- 检索:三函数 "cosine semantic similarity search, Okapi BM25 full-text search, and
  breadth-first search" + reranker(RRF/MMR/cross-encoder)。
- 维护:bi-temporal 双时间轴(边带 t_valid/t_invalid/t'_created/t'_expired),
  失效不删除,保留演化史。

**三家共识 → 对 Zeichen 的意义**:①「双层记忆(常驻摘要层+按需检索层)」三家一致,
即 F5/F21 的外部佐证;②「失效标记而非物理删除」我们已有等价物(版本表+软删);
③「写入时 LLM 自动抽取管线」被 REQ-57/D4 **有意排除**(后端零 LLM,摘要创作侧生成)——
这是 LLM Wiki 与记忆引擎的本质分界:**文档库+结构化接口,不是记忆引擎**。

### 2.7 Claude Code 记忆 / Claude Projects / 开源参照【一手已核】

**Claude Code memory**(code.claude.com/docs/en/memory):
- 知识单元:CLAUDE.md(人写指令;/init 从代码库生成初稿并吸收 AGENTS.md/Cursor 等
  既有文件)+ auto memory(MEMORY.md 索引 + 主题文件,frontmatter type: user/
  feedback/project/reference,**Claude 自写**)。
- **多层作用域按序拼接注入**:managed policy(/etc/claude-code/CLAUDE.md)→ user
  (~/.claude/CLAUDE.md)→ project(./CLAUDE.md)→ local(CLAUDE.local.md)——
  "All discovered files are concatenated into context rather than overriding each
  other";子目录 CLAUDE.md 由 Read/Write/Edit 工具触发**按需加载**;MEMORY.md
  "The first 200 lines … or the first 25KB, whichever comes first";imports
  "@path"(递归 ≤4 跳);.claude/rules/*.md 按 paths glob 作用域;/doctor
  prompt-audit 审过期与冲突。

**Claude Projects**(support.claude.com):项目 = 知识库 + 项目指令;项目名/描述
**不进上下文**("Claude will not have access to these details");项目内全部对话共享;
超限自动降级——"when your project knowledge approaches the context window limit,
Claude will automatically enable RAG mode to expand your project's capacity by up to
10x";检索按文件名引用(官方建议描述性文件名)。

**Open WebUI Knowledge**(docs.openwebui.com,开源参照):双模式——Focused
Retrieval(BM25+向量+rerank)/ Full Context 全文注入;原生函数调用下**不自动注入**,
须模型主动调知识工具;agentic 工具 list/query/grep/view_file,实验性 kb_exec 文件
系统式访问(单次输出 ≤30000 字符);增量目录同步(客户端 SHA-256 diff)。

**ChatGPT Projects**(help.openai.com):chats + files + instructions + app 链接;
可把聊天回复 "Save to project" 存为知识源;project-only memory 隔离。

## 3. 综合参考架构(六域功能模型)

```
┌─ 互操作域 EXPOSE ── MCP(resources+tools) · HTTP 导出(llms.txt/export.md) · 原生插件
├─ 交付域 DELIVER ── 渐进披露(索引→摘要→全文) · 探索工具(get+双链反链/search)
│                    · 组装接口(预算内打包,D7 待裁) · 干净 .md 渲染
├─ 检索域 FIND ───── 关键词索引(pg_trgm) · 多词+过滤+别名 · 相似度+新鲜度排序 · 命中片段
├─ 治理域 GOVERN ─── 溯源标识 · 过期检测(review_date+依赖变化) · 断链/孤儿 · 权限边界
├─ 写入域 WRITE ──── 双通道创作(人编辑器/agent API) · 写入时解析(frontmatter/双链落表)
│                    · 模板 · 版本 · 存量迁移工具
└─ 结构域 ORGANIZE ─ 稳定标识(短码/URI) · frontmatter 元数据 · 双链网络 · 术语层 · 导航结构
```

数据流:**写入**(agent/人)→ 解析落库(结构域)→ 索引(检索域)→ 按需交付(交付域/
互操作域)→ 治理反馈(过期/断链驱动修订)→ 回到写入。双读者原则:同一份数据,
人类走富渲染,agent 走干净 .md + 结构化接口。

## 4. 核心功能点清单(调查合入后定稿优先级)

> P0=缺了不成立;P1=显著增益;P2=锦上添花/可后置。每点注一手参照。
> 【定稿 2026-10-07:两路调查已复核】

**记忆系统校验结论**(§2.6 三家 vs F 清单):双层记忆=F5/F21;失效不删除=版本表+
软删(已有);写入时 LLM 抽取=有意不做(REQ-57/D4);多路混合检索=D1 裁定只取关键词
通道;共享块=项目内天然共享;tag 过滤=F10。**F 清单无需增删**。

| # | 功能点 | 域 | 优先级 | 一手参照 | 说明 |
|---|---|---|---|---|---|
| F1 | 稳定标识(DOC-n 短码/URI,改名不断链) | 结构 | P0 | Zeichen 现有;MCP resource URI | agent 的永久句柄 |
| F2 | frontmatter 元数据(summary/kind/tags/aliases/review_date/owners) | 结构 | P0 | Jekyll;Mintlify(直接原料);Skills(name/description) | 判断材料,不打开全文即可决策 |
| F3 | [[双链]]写入时落表 + 反链查询 | 结构 | P0 | Obsidian;doc_link 表 | 知识成网;图扩展与断链检测的地基 |
| F4 | 干净 .md 读取(无 chrome)+ 元数据结构化返回 | 交付 | P0 | llms.txt v2(.md 版);Skills | 模型吃纯文本 |
| F5 | 渐进披露索引(小索引→摘要→全文) | 交付 | P0 | llms.txt;Skills 三级;DeepWiki structure→contents | token 经济学核心机制;量化参照 Skills:元数据 ~100 tokens 常驻、正文 <5000、主文件 <500 行;MEMORY.md 前 200 行/25KB |
| F6 | 关键词检索+索引加速+命中片段 | 检索 | P0 | pg_trgm(PG 官方);Sourcegraph symf | 可预测的字面匹配;D1 裁定 |
| F7 | agent 写入通道(API 权限+写入时解析管线) | 写入 | P0 | Skills「Iterate with Claude」;Devin(Skills 化) | wiki 要能被 agent 长出来 |
| F8 | 版本+溯源标识(人/agent 创作) | 写入/治理 | P1 | Zeichen 现有版本表;DeepWiki 生成期标注 | 信任信号 |
| F9 | 术语层(glossary+aliases+自动链接) | 结构 | P1 | Zeichen 现有 glossary;Obsidian aliases | 共同词汇,消歧 |
| F10 | 结构化过滤(module/kind/tags)+别名参与匹配 | 检索 | P1 | Mintlify 分节;llms.txt H2 | 收窄候选 |
| F11 | 模板(doc_kind 骨架) | 写入 | P1 | Skills 目录规范;DeepWiki wiki.json | 结构一致性前置到创作 |
| F12 | 断链保留+点击创建+保存时警告 | 写入/治理 | P1 | Obsidian(断链一等节点) | 断链=待办不是错误 |
| F13 | 过期检测(review_date+derives 依赖变化提示) | 治理 | P1 | Zeichen 裁定 D6 | 知识不腐烂 |
| F14 | MCP 暴露(resource template+tools+resource links) | 互操作 | P1 | MCP 规范 | 标准化接入 |
| F15 | llms.txt/export.md HTTP 导出 | 互操作 | P1 | llms.txt v2;Mintlify | 外部工具可用 |
| F16 | 组装接口(预算内上下文打包,带出处) | 交付 | P2(D7 待裁) | Mintlify context 端点;Anthropic 子代理蒸馏 | 时机问题:语料大后价值升 |
| F17 | 存量迁移工具(一次性补 summary 等) | 写入 | P2 | Mem0/记忆系统管线(待补) | 存量 61 篇 |
| F18 | unlinked mentions(未成链提及) | 结构 | P2 | Obsidian | 发现潜在链接 |
| F19 | 体检报告(质量信号) | 治理 | 不做 | — | D6 裁定;二期再议 |
| F20 | 记忆式动态层(时序图/自动提取) | 全域 | 不做 | Zep/Mem0(调查中,作参照) | REQ-57 教训:后端零 LLM 依赖 |
| F21 | 项目级常驻入口(作用域注入:每项目一份「入口文档」自动进 agent 会话) | 交付 | P2 | Claude Code 四层 CLAUDE.md 拼接;Projects 指令 | 等于给项目配 CLAUDE.md;可由入口页/llms.txt 承担,待 W3 定 |
| F22 | 引用包含(@import 式跨文档组合) | 结构 | P2 | Claude Code imports(≤4 跳);Skills 一层深引用 | 观察项,不进一期 |

## 5. Zeichen 映射

- **已有**:F1(短码+标题唯一)、F8 版本半(F9 glossary 已有 27 词条)、树形工作台、
  实体引用 ref API、评论、附件;`doc_metadata` JSON 列现成可装 frontmatter。
- **待建**:W1=F2/F3/F9/F11/F12;W2=F6/F10;W3=F5/F4/F15/F14(+F16 视 D7);
  W4=F13/F8 溯源半。F7 = 现有 MCP/API 通道加解析管线。
- 数据模型唯一新增表:`doc_link`(D5 已裁定写入时落表);`Document` 表不改列。

## 6. 调查覆盖与诚实边界

- **一手来源**(全部 web_fetch 核实):llms.txt v2 规范、Mintlify 文档/Index API、
  DeepWiki 博客+官方文档、Agent Skills 工程博客+agentskills.io 规范、Claude Code
  memory 文档、Claude Projects 帮助、Open WebUI 文档、ChatGPT Projects 帮助、
  Letta/Mem0/Zep 官方文档与论文、MCP 规范、PostgreSQL pg_trgm、Obsidian 帮助、
  Jekyll frontmatter(共 15 类);检索哲学面(Cline/Cursor/Anthropic/Cody)见
  [llm-wiki-survey-20261007.md](llm-wiki-survey-20261007.md)。
- **「自动注入 vs 按需加载」分界证据**(§2.7):Claude Code 常驻拼接+子目录按需;
  Projects 超限才降级检索;OpenWebUI 原生函数调用下不自动注入——共识是**默认不注入、
  索引常驻、正文按需**,F5/F21 据此设计。
- **查不到/未覆盖**(各系统官方文档均未覆盖):DeepWiki 聚类算法细节;Claude Projects
  单文件大小/格式限制;Claude Code README 学习机制;Skills 版本更新机制;Letta 衰减/
  修订历史;Mem0 多 agent 共享;Zep prompt 注入策略。另:MediaWiki 文档抓取超时;
  OpenAI llms.txt(403)与 developers.openai.com/codex 无法核验;Cursor 旧版
  codebase-indexing 文档页已下线重定向。
- **移植边界**:无一参考系统与「项目 wiki + 61 篇 + agent 消费」同构,§4 优先级是
  按 Zeichen 约束(后端零 LLM、纯关键词、pg 单库)做的工程判断,非照抄。
