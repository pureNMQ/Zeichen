# Karpathy「LLM Wiki」调查(2026-10-07)

> **为什么要单独调查它**:此前两轮调研的对象是「面向 LLM 阅读的知识库」(检索/交付/
> 渐进披露——LLM 是**读者**)。Karpathy 的 LLM Wiki 是极性相反的一件事:**LLM 是作者
> 和维护者**,知识被「编译」进 wiki 而非每次查询时「检索」。两者共用 wiki 这个词,
> 重心完全不同。本文以一手材料为准呈现他的原意。
>
> **出处与核实状态**:
> - 一手(全文已核实,原文存档于 [karpathy-llm-wiki-gist-20260404.md](karpathy-llm-wiki-gist-20260404.md)):
>   GitHub Gist "LLM Wiki" idea file,2026-04-04,
>   [gist.github.com/karpathy/442a6bf555914893e9891c11519de94f](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
> - 一手(经媒体转述,x.com 无法直接核验):起始推文 "LLM Knowledge Bases"
>   (2026-04-02,[x.com/karpathy/status/2039805659525644595](https://x.com/karpathy/status/2039805659525644595))
>   与 Farzapedia 评论推文([2040470801506541998](https://x.com/karpathy/status/2040470801506541998))
> - 二手(仅用于传播数据与生态响应,已标注):新智元(网易)、dev.to、hrsrini 等

---

## 1. 核心思想:编译,不是检索

对 RAG 的批判(Gist 原文):

> "This works, but the LLM is rediscovering knowledge from scratch on every question.
> **There's no accumulation.** … Nothing is built up. NotebookLM, ChatGPT file uploads,
> and most RAG systems work this way."

他的替代方案:

> "Instead of just retrieving from raw documents at query time, the LLM **incrementally
> builds and maintains a persistent wiki** … It reads it, extracts the key information,
> and integrates it into the existing wiki — updating entity pages, revising topic
> summaries, noting where new data contradicts old claims, strengthening or challenging
> the evolving synthesis. **The knowledge is compiled once and then kept current, not
> re-derived on every query.**"

关键性质:**wiki 是持久的、复利的制品**("a persistent, compounding artifact")——
交叉引用已经建好、矛盾已经标出、综合已反映读过的所有东西。

人机分工:

> "You never (or rarely) write the wiki yourself — **the LLM writes and maintains all
> of it.** You're in charge of sourcing, exploration, and asking the right questions.
> The LLM does all the grunt work — the summarizing, cross-referencing, filing, and
> bookkeeping."

最著名的一句类比(他自己的工作方式:一边开 LLM agent、一边开 Obsidian 实时看它改):

> "**Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase.**"

## 2. 架构:三层 + 两个特殊文件

| 层 | 内容 | 规则 |
|---|---|---|
| raw/ 原始资料 | 文章、论文、图片、数据 | **不可变**——"the LLM reads from them but never modifies them. This is your source of truth." |
| wiki/ 知识层 | LLM 生成的 markdown 页:摘要页、实体页、概念页、对比页、overview、synthesis | **LLM 完全拥有**——"You read it; the LLM writes it." |
| schema 规则层 | CLAUDE.md / AGENTS.md | 告诉 LLM 结构、约定、工作流;**它使 LLM 从「带文件访问的聊天机器人」变成「有纪律的 wiki 维护者」**;人与 LLM 共同进化此文件 |

两个特殊文件:

- **index.md(内容向目录)**:每页一行链接+一句话摘要+元数据,按类别组织,**每次
  ingest 都更新**。查询时 LLM 先读 index 再钻取页面。"This works surprisingly well
  at moderate scale (**~100 sources, ~hundreds of pages**) and **avoids the need for
  embedding-based RAG infrastructure**."
- **log.md(时间向日志)**:append-only,记录 ingest/query/lint;统一前缀
  (`## [2026-04-02] ingest | Article Title`)使其可被 unix 工具直接解析
  (`grep "^## \[" log.md | tail -5`)。

## 3. 三个操作

1. **Ingest**:新资料进 raw/,LLM 读→与人讨论要点→写摘要页→更新 index→**联动更新
   相关实体/概念页**→追加 log。**单一来源可能触及 10–15 个 wiki 页**。Karpathy 个人
   偏好一次一篇、人在环("I read the summaries, check the updates, and guide the LLM
   on what to emphasize");也允许批量低监督。
2. **Query**:对 wiki 提问。LLM 先读 index 找相关页→读页→**带引用**综合作答;输出
   可以是 markdown/对比表/Marp 幻灯片/matplotlib 图/canvas。**好答案回填为 wiki
   新页**("good answers can be filed back into the wiki as new pages")——你的探索
   与 ingest 一样产生复利。
3. **Lint**:定期体检——页间矛盾、被新来源取代的过期论断、无入链的孤儿页、被提及
   但没有独立页的概念、缺失的交叉引用、可用 web 搜索补全的数据缺口;LLM 还擅长
   建议下一步该研究什么。

## 4. 检索观:索引优先,检索是可选件

- 中等规模(~100 来源/数百页)下,**index.md + 摘要就够,不需要嵌入/RAG 基建**(原文)。
- wiki 长大后可加本地搜索引擎:他点名 [qmd](https://github.com/tobi/qmd)(本地 markdown
  搜索,BM25/向量混合 + LLM 重排,带 CLI 与 MCP server)。"at small scale the index
  file is enough, but as the wiki grows you want proper search."
- 工具箱其他件:Obsidian Web Clipper(网页转 markdown 入 raw)、图片本地化(防失效+
  LLM 可看)、graph view(看 wiki 形态)、Marp(出幻灯片)、Dataview(frontmatter
  查询)、**"The wiki is just a git repo of markdown files"**(版本/分支/协作白拿)。

## 5. 为什么成立:bookkeeping 瓶颈被消除

> "The tedious part of maintaining a knowledge base is not the reading or the thinking —
> it's the **bookkeeping**. … Humans abandon wikis because the maintenance burden grows
> faster than the value. **LLMs don't get bored, don't forget to update a cross-reference,
> and can touch 15 files in one pass.** The wiki stays maintained because the cost of
> maintenance is near zero."

思想谱系:Vannevar Bush《As We May Think》(1945)的 Memex——个人化、持续策展、
关联线索比文档本身更有价值。"The part he couldn't solve was who does the maintenance.
**The LLM handles that.**"

## 6. 场景(他列的清单)

个人(目标/健康/心理,日记+文章+播客笔记→关于自己的结构化图景)、研究(数周数月深挖
一题, evolving thesis)、读书伴侣 wiki(逐章归档,人物/主题/线索,例:Tolkien Gateway
式的个人版)、**商业/团队**、竞争分析、尽调、行程规划、课程笔记、爱好深挖。

团队场景原文值得整段引用:

> "**Business/team**: an internal wiki maintained by LLMs, fed by Slack threads, meeting
> transcripts, project documents, customer calls. **Possibly with humans in the loop
> reviewing updates.** The wiki stays current because the LLM does the maintenance that
> no one on the team wants to do."

## 7. 四个优势(其评论 Farzapedia 的推文,经中文媒体转述,标注:一手推文/二手转述)

1. **Explicit(显式)**:知识不在 AI 的隐式黑箱记忆里,而是可见、可导航、可检视的制品;
2. **Yours(你的)**:数据在本地,不锁在厂商云端;
3. **File over App(文件优于应用)**:纯 markdown+图片,任何工具任何 agent 都能操作;
4. **BYOAI(自带 AI)**:Claude/Codex/开源模型随便换,甚至可拿 wiki 微调专属模型。

## 8. 生态响应(二手,供参考)

- 起始推文数天 1200–1600 万浏览;Gist 首周 ~5000 star、4282 fork(二手:hrsrini/
  新智元汇总);他自述研究 wiki 约 100 篇文章/40 万字(二手转述)。
- **Farzapedia**(开发者 Farza 实例):2500 条日记/Apple Notes/iMessage 编译成 400 篇
  结构化文章的「关于自己的百科」,**给 AI agent 用**:agent 从 index.md 起沿链接爬取;
  新增内容自动归入 2–3 篇既有页或开新页(二手:新智元)。
- 批评面(二手 dev.to 的诚实对比表):LLM 压缩转写有**幻觉固化**风险(错的东西被写成
  「事实」并沿链接传播,RAG 的错误只停留在单次回答);答案离原始来源 1–2 步;适合
  ~100–500 来源的策展语料,不适合百万级文档的事实查询;更新需重新 ingest。

## 9. 与此前全景调查的关系:极性反转

在 [llm-knowledge-systems-landscape-20261007.md](llm-knowledge-systems-landscape-20261007.md)
的八家族里,这件事横跨两族、但不等于任何一族:

- 骨架像 **D 族(指令/技能文件)**:markdown 文件 + CLAUDE.md schema + 文件系统即接口;
- 灵魂是 **E 族的「写入侧」**:LLM 自动抽取/整合/维护——但 E 族做成**服务端产品**
  (向量库/图引擎/管线),他做成**个人文件目录上的 pattern**,无服务、无基建、无索引
  起步(index-first);
- 与 A–D 族的交付面(渐进披露/检索/组装)几乎正交:那些解决「怎么喂给模型」,
  这件事解决「**知识怎么积累**」——查询侧只需要 index+跟链这一最简形态。

一句话:**此前调研的全部家族在优化「LLM 读」;Karpathy 的 LLM Wiki 在定义「LLM 写」,
读侧靠 LLM 自己维护的高质量 index 即可成立。**

## 10. 诚实边界

- Gist 全文为一手且已存档;推文文字、浏览量/star 数、Farzapedia 细节、四优势均为
  媒体转述(x.com 无法直接核验),已逐处标注。
- 该 pattern 是**想法文件**(intentionally abstract):Karpathy 明确不提供具体实现,
  "The document's only job is to communicate the pattern. Your LLM can figure out
  the rest."——不存在「官方架构」可照抄,只有 pattern 与若干推荐件(qmd/Obsidian/
  Marp/Dataview)。
