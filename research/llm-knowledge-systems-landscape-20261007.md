# LLM 知识系统全景:大家都是怎么做的(2026-10-07)

> **目标**:客观呈现业界构建「面向 LLM 的知识库/Wiki」的实际做法。本文**不含任何
> 特定项目的映射、裁定或倾向**——只回答:谁在做什么、每个维度上具体怎么做(含参数)、
> 分歧在哪、各自前提是什么。
> **方法**:只用一手来源(官方文档/博客/规范/论文),全部经 web_fetch 拉原文核实,
> 引文 verbatim,事实逐条注出处。**八个家族已全部覆盖,2026-10-07 定稿。**

---

## 1. 家族图谱:谁在做 LLM 知识系统

| 家族 | 代表 | 一句话形态 | 一手材料形态 |
|---|---|---|---|
| A 静态导出协议 | llms.txt v2 规范、Mintlify(规模化实现) | 站点旁挂机器可读索引 + 干净 .md,agent 拉取 | 规范全文 + 官方文档 |
| B 生成式 wiki | DeepWiki(Cognition/Devin) | 从代码库自动生成 wiki 页面树 + 问答 | 官方博客 + 官方文档 |
| C 会话项目知识 | Claude Projects、ChatGPT Projects | 每项目上传文档,超限自动切检索 | 官方帮助中心 |
| D 指令/技能文件 | CLAUDE.md(Claude Code)、Agent Skills(开放标准) | 仓库/技能目录内文件,分层作用域注入 | 官方文档 + 开放规范 |
| E agent 记忆引擎 | Letta(MemGPT)、Mem0、Zep(Graphiti) | 运行时自动抽取事实/图,动态写入 | 官方文档 + 论文 |
| F RAG 管线平台 | LlamaIndex、LangChain、Open WebUI KB、Microsoft GraphRAG | 分块 + 嵌入 + 检索 + 重排的组装管线;图变体:KG + 社区摘要 | 官方文档 + 论文 + 源码默认值 |
| G 商业 wiki 的 AI 层 | Notion AI、Guru | 既有 wiki/知识源上加 AI 问答(带引用与权限过滤) | 官方帮助中心 |
| H 代码库检索 | Cursor、Sourcegraph Cody、Cline、Claude Code | 代码语料上的索引/检索/探索(公开数据最丰富) | 官方研究博客 + 官方文档 |
| I 自维护编译式 wiki(个人范式) | Karpathy「LLM Wiki」(2026-04 idea file) | LLM 读不可变 raw/ 资料,「编译」并持续维护一套 wiki/,人负责选题与提问;index-first,无 RAG 基建 | Gist 原文(一手,已存档)+ 推文(二手转述) |

## 2. 六个维度的做法分布

### 2.1 知识怎么进去(写入路径)

| 做法 | 系统 | 出处事实 |
|---|---|---|
| 人工编写 | llms.txt(站点作者)、Skills(技能作者)、CLAUDE.md(开发者) | Claude Code 的 /init 可从代码库生成初稿并吸收 AGENTS.md 等既有文件;Skills 有 skills-ref validate 校验 |
| 用户上传 | Claude Projects、ChatGPT Projects | ChatGPT 可把聊天回复 "Save to project" 存为知识源 |
| 部署时自动生成 | Mintlify | "Mintlify automatically hosts an llms.txt file at the root of your project… always up to date and requires zero maintenance" |
| 全自动生成 | DeepWiki | 索引仓库→聚类规划成页;"When a config file is present, we bypass the default cluster-based planning and create exactly the pages you specify"(wiki.json 人工舵控) |
| 运行时自动抽取 | Mem0、Zep、Letta | Mem0 两阶段("extraction and update"),更新期 LLM tool-call 四操作:"ADD…; UPDATE…; DELETE for removal of memories contradicted by new information; and NOOP…";Zep 全自动管线(实体抽取→消歧→事实/时间抽取) |
| agent 自写 | Claude Code auto memory(MEMORY.md+主题文件,Claude 自写)、Letta 块自编辑 | Anthropic 对 Skills 的官方建议:"ask Claude to capture its successful approaches… into reusable context" |
| 外部源同步 | Guru | 连接 Slack/Drive/Salesforce 等建索引:"Guru checks for changes multiple times per day";权限双模式(尊重源应用原生 ACL,或以单用户身份索引) |
| 工作区自动索引 | Notion AI | "Notion receives an embedding for each Notion page and stores it in a vector database (e.g., Turbopuffer)"(OpenAI 零保留嵌入 API);新内容约 1 小时后可被引用 |
| LLM 增量编译维护 | Karpathy LLM Wiki | ingest 时 LLM 读新源→写摘要页→更新 index→**联动更新 10–15 个相关页**→记 log;"The knowledge is compiled once and then *kept current*, not re-derived on every query";"You never (or rarely) write the wiki yourself — the LLM writes and maintains all of it" |

### 2.2 知识怎么组织(单元与结构)

| 组织方式 | 系统 | 事实 |
|---|---|---|
| 整页/整文件 | llms.txt 系、Claude/ChatGPT Projects | llms.txt v2:同 URL 出 .md 干净版,rel="alternate"/"describedby" 发现 |
| 分块(chunk) | LlamaIndex、LangChain、Cursor | LlamaIndex:"…chunk them into `Node` objects, such that each node is a specific chunk of the parent document";SentenceSplitter 尊重句子边界;Markdown/HTML 按结构切(HTML 默认标签 p/h1–h6/li 等);LangChain RecursiveCharacterTextSplitter 递归分隔符 ["\n\n","\n"," ",""];Cursor 按语法块切(AST 感知)+缓存;默认数值见 §3 |
| 层级分块(小检大回) | LlamaIndex、LangChain | HierarchicalNodeParser 默认 [2048,512,128] + AutoMergingRetriever;SentenceWindowNodeParser 嵌入用单句、交付用邻域窗口(window_size=3);LangChain ParentDocumentRetriever "first fetches the small chunks but then looks up the parent IDs… and returns those larger documents" |
| 知识图谱+社区摘要 | Microsoft GraphRAG | LLM 抽实体/关系/claims 建 KG;"we use Leiden community detection… in a hierarchical manner, recursively detecting sub-communities",自底向上逐层生成社区摘要 |
| 常驻块+按需库 | Letta | block(label/value/limit/read_only)常驻;archival passage(content+tags,单条 ≤300 tokens)向量库 |
| 事实/图 | Mem0、Zep | Mem0 抽取式「事实」;graph 变体=实体+有向边。Zep 三层子图:episode("non-lossy data store")→entity(名称+摘要+1024 维向量)→community(簇摘要) |
| 页面树+控制文件 | DeepWiki | wiki.json:pages[{title 唯一,purpose,parent,page_notes}]+repo_notes,显式 parent 层级 |
| 技能目录 | Agent Skills | SKILL.md + scripts/(可执行)+ references/(文档)+ assets/(模板) |
| 层级作用域文件 | Claude Code | 四层:managed policy → user → project → local;"All discovered files are concatenated into context rather than overriding each other";.claude/rules/*.md 按 paths glob 作用域 |
| 双链网络 | Obsidian(通用笔记事实标准) | [[name]]/[[name\|display]]/[[name#heading]];反链面板 Linked/Unlinked mentions;断链是图中一等节点("a note doesn't need to exist to link to it"),点击即创建 |

### 2.3 检索怎么做

| 做法 | 系统 | 事实 |
|---|---|---|
| 无内建检索,靠索引跟链 | llms.txt 规范本身 | "Agents are expected to view or search llms.txt… then follow the relevant links" |
| 关键词/字面 | Sourcegraph Cody、Cline、Claude Code、Open WebUI(一路) | Cody:"Cody uses symf, a local keyword search engine, to create and maintain code indexes";Claude Code 用 "glob and grep… effectively bypassing the issues of stale indexing and complex syntax trees";Zep 三检索函数之一是 "Okapi BM25 full-text search";Open WebUI Focused Retrieval 含 BM25 |
| 语义向量 | Letta、Mem0、Cursor | Cursor 自训 embedding:"semantic search significantly improves agent performance, especially over large codebases"(问答准确率平均 +12.5%,6.5–23.5%) |
| 多路混合+重排 | Zep、Mem0 平台、Open WebUI、Cursor | Zep:"cosine semantic similarity search, Okapi BM25 full-text search, and breadth-first search"+reranker(RRF/MMR/cross-encoder);Mem0 平台融合 semantic/keyword/entity/temporal;Cursor:"the combination of these two (grep+semantic) leads to the best outcomes";Sourcegraph 官方检索=Keyword+Embeddings+Search+Code Graph 四路混合 |
| 问答式(检索即服务) | DeepWiki(ask_question)、Claude Projects(RAG 模式) | Projects 超限时用 project knowledge search tool 按需检索,低于阈值自动切回 |
| 图遍历 | Zep | BFS 出入边子图检索 |
| LLM 生成查询再检索 | Notion AI、LangChain SelfQueryRetriever | Notion:LLM 生成搜索查询→向量库取页→交 LLM "refined and ranked by relevance";SelfQueryRetriever "uses a vector store and an LLM to generate the vector store queries" |
| 融合检索 | LlamaIndex、LangChain | LlamaIndex QueryFusionRetriever:向量+BM25、RRF 合并并生成扩展查询;LangChain EnsembleRetriever "uses a rank fusion"(加权 RRF) |
| 验证知识+引用 | Guru | "based on your team's verified knowledge, with citations linking to the sources used";Answer Details 展示推理与具体所用源;算法内部不公开 |
| 局部图+文本 / 全局社区摘要 | GraphRAG | Local:"combining relevant data from the AI-extracted knowledge-graph with text chunks of the raw documents";Global:"searching over all AI-generated community reports in a map-reduce fashion" |

### 2.4 怎么进上下文(交付机制)

| 机制 | 系统 | 事实 |
|---|---|---|
| 常驻注入 | CLAUDE.md 四层拼接、Letta 块、Skills 第一级 | Letta 块 "always visible - no retrieval needed";Skills:"Metadata (~100 tokens): The name and description fields are loaded at startup for all skills" |
| 按需加载 | Skills 第二/三级、llms.txt 跟链、DeepWiki MCP | DeepWiki MCP 三工具 read_wiki_structure / read_wiki_contents / ask_question(结构→内容→问答) |
| 超限自动切换 | Claude Projects、Open WebUI | Projects:"when your project knowledge approaches the context window limit, Claude will automatically enable RAG mode to expand your project's capacity by up to 10x";Open WebUI 双模式(Full Context vs Focused Retrieval),原生函数调用下不自动注入,须模型主动调知识工具 |
| 预算组装 | Mintlify Index API | context 端点:按 token 预算返回带出处引用的组装内容("ready-to-use context in one request"),与 search/contents 原语并存 |
| 子代理蒸馏 | Anthropic 官方模式 | "Each subagent might explore extensively, using tens of thousands of tokens or more, but returns only a condensed, distilled summary (often 1,000-2,000 tokens)" |
| 索引规模化拆分 | Mintlify | 单索引 >100,000 字符自动拆 `/_llms/` 递归子索引 |
| 三段式组装管线 | LlamaIndex | Retrieval → Postprocessing(重排在此:"after the node retrieval step and before the response synthesis step")→ Response synthesis(response_mode:default/compact/tree_summarize/no_text/accumulate) |
| map-reduce 全局组装 | GraphRAG、LangChain | GraphRAG global:"the summaries are used to provide partial answers to the query independently and in parallel, then in the reduce step, the partial answers are combined";LangChain load_summarize_chain:"stuff"、"map_reduce"、"refine"(默认 stuff) |

### 2.5 怎么维护(时效与冲突)

| 做法 | 系统 | 事实 |
|---|---|---|
| 部署时自动同步 | Mintlify | "always up to date"(随部署再生成) |
| 显式 regenerate | DeepWiki | 提交 wiki.json 后 regenerate;版本/过期策略:文档未覆盖 |
| 时间失效(双时间轴) | Zep | 边带 t_valid/t_invalid/t'_created/t'_expired;"Graphiti consistently prioritizes new information when determining edge invalidation";失效不删除,保留演化史 |
| 失效标记不删除 | Mem0(graph 版) | "marking them as invalid rather than physically removing them to enable temporal reasoning" |
| 写时冲突消解 | Mem0、Letta | Mem0 四操作决策;Letta 块整段替换、并发 last-write-wins(memory_insert 追加安全、memory_rethink 非并发安全) |
| 审计工具 | Claude Code | /doctor prompt-audit 查过期/冲突;memory 文件记 modified ISO 时间戳 |
| 版本化 | Skills | metadata(version)、license/compatibility 字段;更新机制:规范未覆盖 |
| 断链治理 | Obsidian | 断链=一等节点+点击创建;反链面板含 Unlinked mentions(未成链提及) |
| 索引刷新 API | LlamaIndex | Index 提供 insert/delete/update/refresh |
| 异步索引+删除时限 | Notion | "It can take around an hour before new content… is referenced by Q&A";删除后嵌入 "deleted within 60 days" |

### 2.6 谁能写(人 / agent)

| 系统 | 人写 | agent 写 |
|---|---|---|
| llms.txt / Mintlify | ✅(作者/部署管线) | — |
| CLAUDE.md | ✅(/init 辅助) | auto memory 完全由 Claude 自写 |
| Agent Skills | ✅ | 官方倡导("Iterate with Claude");产品规划"enable agents to create, edit, and evaluate Skills on their own" |
| Claude/ChatGPT Projects | ✅(上传) | —(ChatGPT 可存聊天回复为知识源) |
| DeepWiki | wiki.json 舵控 | 全自动生成 |
| Letta / Mem0 / Zep | 开发者 API 旁路 | 核心通道(agent 运行时写) |
| Notion AI / Guru | ✅(页面/Card 作者 + 外部源) | —(索引管线自动) |
| Karpathy LLM Wiki | 仅 raw/ 与 schema(人策划来源、定规则) | **wiki/ 整层由 LLM 拥有**("You read it; the LLM writes it");lint 也由 LLM 执行 |

## 3. 参数与数字惯例(客观事实表)

| 系统 | 参数 | 值 |
|---|---|---|
| Agent Skills | 元数据常驻量 | "~100 tokens"(name+description,全部技能) |
| Agent Skills | 正文建议 | <5000 tokens;"Keep your main SKILL.md under 500 lines" |
| Agent Skills | 字段限长 | name ≤64 字符(小写/数字/连字符);description ≤1024;compatibility ≤500 |
| Agent Skills | 文件引用 | "one level deep from SKILL.md" |
| Claude Code | MEMORY.md 加载量 | "The first 200 lines … or the first 25KB, whichever comes first" |
| Claude Code | CLAUDE.md | 上限 4MiB,建议 <200 行;imports 递归 ≤4 跳 |
| Mintlify | 页描述 | 取 frontmatter description 首段,截 300 字符 |
| Mintlify | 索引拆分阈值 | 100,000 字符 → /_llms/ 递归子索引 |
| DeepWiki | 页数 | ≤30 页(企业 80);总 notes ≤100;repo_note ≤10000 字符;三档 effort |
| Letta | 常驻块 | <50k chars、<20 个;文件 5MB、<100;archival 单条 ≤300 tokens |
| Letta | 选型官方口径 | "For smaller amounts of data, it is best to simply place everything into the context window with memory blocks" |
| Claude Projects | 超限策略 | 自动 RAG,"up to 10x" 容量;文件数按套餐 5/25/40(ChatGPT) |
| Open WebUI | 工具输出 | kb_exec 单次 ≤30000 字符 |
| Zep | 向量维度 | entity 1024 维 |
| LlamaIndex | chunk 默认 | chunk_size=1024 tokens、chunk_overlap=20 tokens(源码 llama-index-core/constants.py);层级 [2048,512,128];SentenceWindow window_size=3;VectorStoreIndex 插入批 2048;SimilarityPostprocessor 示例阈值 0.7/0.75;示例 top-k 2 或 10 |
| LangChain | chunk 默认 | TextSplitter chunk_size=4000、chunk_overlap=200(源码 text-splitters base.py);递归分隔符 ["\n\n","\n"," ",""];summarize chain_type 默认 'stuff' |
| GraphRAG | 语料与参数 | 实验语料 ~1M token 量级;map 有用度 0–100、0 分滤除 |
| Notion AI | 规模与时效 | 官方建议工作区 ≥100 页;新内容 ~1 小时可引用;嵌入删除 ≤60 天 |
| Guru | 限制 | 单文件 ≤500MB(PNG 10MB)、≤3000 页;每日多次变更检查 |

## 4. 关键分歧与各自前提(客观并列,不裁决)

1. **整篇 vs 分块**。整篇:llms.txt 系、Projects、Letta 块("place everything into the
   context window")。分块:RAG 平台、Cursor。前提差异:Cline 一方 "when you chunk
   code for embeddings, you're literally tearing apart its logic";Cursor 一方实测
   语义分块检索在 ≥1000 文件库带来 +12.5% 问答准确率(小库无此收益数据)。
   **中间形态已是平台主流**:层级分块+AutoMerging(小检大回)、SentenceWindow
   (单句嵌入+窗口交付)、ParentDocumentRetriever(chunk 检索、父文档交付)——
   分块只用于检索,交付回大单元。GraphRAG 论文另指 "vector RAG approaches do not
   support sensemaking queries"(全局综合类问题),此为其引入社区摘要的动机。
2. **字面 vs 语义 vs 混合**。纯字面可用:Cline/Claude Code(grep/glob)。语义为主:
   Letta/Mem0/Cursor。多家终点是混合:Cursor("grep+semantic… best outcomes")、
   Zep(3 函数+reranker)、Mem0 平台(4 信号)、Sourcegraph(4 路)、Open WebUI(BM25+
   向量+rerank)。闭源商业侧(Notion/Guru)只公开到「嵌入向量库+LLM 重排」「验证
   知识+引用」粒度,分块与排序参数不公开。
3. **常驻注入 vs 按需取用**。常驻:CLAUDE.md/Letta 块/Skills 一级。按需:llms.txt/
   Skills 二三级/DeepWiki。切换式:Projects 超限自动 RAG。Anthropic 官方同时给出双向
   事实:"runtime exploration is slower than retrieving pre-computed data"、agent 会
   "chasing dead-ends";而 Claude Code 用 grep/glob "bypassing… stale indexing",
   其官方 best practices 又把 "The infinite exploration"(读几百个文件填满上下文)
   列为失败模式,修复是"Scope investigations narrowly or use subagents"。
4. **人工策划 vs 自动生成 vs 运行时抽取**。人工:Skills/CLAUDE.md/Projects。自动生成:
   DeepWiki(+人工舵控)。运行时抽取:Mem0/Zep/Letta。前提:内容稳定性、信任与审计
   要求、是否接受服务端 LLM 管线(费用/延迟/可靠性)。
5. **失效即删 vs 标记保留**。保留派(Mem0-g/Zep)为时序推理;覆盖派(Letta/CLAUDE.md)
   换取简单。Letta 官方承认衰减/修订历史"文档未覆盖"。
6. **服务端智能 vs 零服务端智能**。服务端 LLM 管线:Mem0/Zep/DeepWiki/Mintlify Index
   (组装)。零服务端智能:llms.txt/Skills/CLAUDE.md(文件即接口)。
7. **嵌入出域的安全面**。Cline:"嵌入是 IP 的第二副本,you've just doubled your
   security surface";Cursor 以 "secure codebase indexing" 为题用 Merkle+块级缓存+
   simhash 声明索引不出本机/受控环境。

## 5. 覆盖与缺口

- **八个家族全部覆盖**(F/G 已于 2026-10-07 合入;GraphRAG 论文编号经更正:
  arXiv:2404.16130 "From Local to Global",初拟 2404.16135 为无关量子论文)。
- 2026-10-07 晚补充家族 I(Karpathy「LLM Wiki」):详见
  [karpathy-llm-wiki-20261007.md](karpathy-llm-wiki-20261007.md)——它与 A–H 的极性
  相反:A–H 优化「LLM 读」,I 定义「LLM 写与维护」,读侧仅靠 index.md+跟链。
- **一手可得性差异**:代码工具(H)与记忆引擎(E)公开最充分(研究博客+论文+文档);
  静态协议(A)有规范全文;商业会话产品(C)只到帮助中心粒度;商业 wiki AI(G)
  内部机制通常不公开。
- **各系统官方未覆盖**(诚实记录):DeepWiki 聚类算法;Claude Projects 单文件限制;
  Claude Code README 学习机制;Skills 版本更新机制;Letta 衰减;Mem0 多 agent 共享;
  Zep 注入策略;MediaWiki 文档(超时);OpenAI llms.txt(403);Cursor 旧版索引文档
  (已下线重定向);LangChain 现行文档 BM25 集成页 404(BM25 官方集成页在 LlamaIndex
  侧);LlamaIndex chunk_overlap 默认值文档页未标注(取自源码 20);Notion/Guru 的
  分块、top-k、嵌入维度、排序权重;GraphRAG 增量索引维护。
