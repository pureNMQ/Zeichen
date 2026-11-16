# 设计稿:Zeichen LLM Wiki——过程记录式(Karpathy 范式移植)(2026-10-07)

> **定位**:用户已定向——在 Zeichen 中搭建「类似 Karpathy LLM Wiki 的管理模式与系统」。
> **状态:定稿 v1(2026-10-07,Q1′–Q6 全部裁定完毕,用户已终审并立项 REQ-59)**:
> 范式定位 + 系统设计 + 裁定台账 + 分期。REQ 草案见 [req-draft-llm-wiki-20261007.md](req-draft-llm-wiki-20261007.md)。
> 一手依据:[Karpathy Gist 原文](karpathy-llm-wiki-gist-20260404.md)(已存档)及
> [调查拆解](karpathy-llm-wiki-20261007.md)。
> 与既有文档的关系:本方向**取代** [llm-wiki-system-design-20261007.md](llm-wiki-system-design-20261007.md)
> 的框架地位(其 D1–D7 裁定哪些保留/弱化/重议见 §5);调查文档保留为依据。

---

## 0. 系统定位(用户 2026-10-07 裁定)

**双系统,双读者(人 + Agent)**:

- **看板系统(需求/任务)= 动态**:告诉人和 Agent 项目做过什么、正在做什么、将要做什么(the what);
- **文档系统(wiki)= 原因**:告诉人和 Agent 为什么做这些东西、为什么出现这样的事故、
  为什么项目有这样的偏好(the why)。

**范式移植范围修正(用户同日裁定)**:Karpathy 的 raw→wiki「编译」管线与 Zeichen 场景
冲突——**wiki 不是从一套原始文件编译来的,而是在软件开发/游戏开发过程中不断记录而来**。
从 Karpathy 范式移植的是运作方式而非输入形态:**知识持续积累(反「无积累」)、结构由
LLM 维护(交叉引用/INDEX/一致性)、index-first 阅读、lint 体检、好答案回填**;
写入的触发源是开发过程本身(看板事件、事故、讨论、决策),不是外部资料库。

**系统边界原则(用户 2026-10-07 裁定)**:Zeichen 只是团队协作系统,**不强制用户记录**;
agent 何时记录、为什么记录,是 **agent harness 的范畴,与 Zeichen 无关**。Zeichen 提供
的是承载与信号:结构、存储、双链、检索、lint 客观信号;约定本身也在系统外
(use-zeichen skill 与团队自理);一切「该不该现在写」的判断在 harness 侧。

## 1. 目标范式(Karpathy 原文蒸馏,作为运作方式参照)

1. **编译,不是检索**:"The knowledge is compiled once and then kept current, not
   re-derived on every query" —— 知识在 ingest 时被 LLM 整理进一套持久、复利的 wiki。
2. **三层**:raw(不可变来源)/ wiki(LLM 完全拥有)/ schema(给 LLM 的维护规则)。
3. **三操作**:Ingest(一源联动 10–15 页)、Query(先 index 后钻页,好答案回填)、
   Lint(矛盾/陈旧论断/孤儿页/缺页体检——语义类,归 skill 侧)。
4. **两个特殊文件**:index.md(内容目录,查询入口,"~100 sources 内不需要 RAG")+
   log.md(append-only 时间线,可 grep)。
5. **人机分工**:人负责选题、提问、思考;LLM 负责全部 bookkeeping。
6. **团队场景**(他原文列的用例之一):"an internal wiki maintained by LLMs, fed by
   Slack threads, meeting transcripts, project documents, customer calls. Possibly
   with humans in the loop reviewing updates."
7. **读侧在范式内的位置**:Query 是核心操作(INDEX→钻页→带引用作答→**好答案回填**,
   读反哺写);他自己一边开着 Obsidian 实时浏览人读视图;且 wiki 长大后要加本地搜索
   qmd("at small scale the index file is enough, but as the wiki grows you want
   proper search")——**写是为了更好的读,读是写的原因与终点**。

## 2. 现状实测:Zeichen 已有什么(逐元素映射)

| Karpathy 元素 | Zeichen 现状(2026-10-07 实测) | 差距 |
|---|---|---|
| 文件系统 markdown 库 | Document(数据库):DOC-n/TERM-n 稳定短码、项目内标题唯一、全量版本表、Vditor 编辑器 | 无差距,形态不同(DB 非文件);短码>文件路径(改名不断链) |
| [[交叉引用]] 由 LLM 维护 | 正文 `[[` 使用率 0;D5 已裁定 doc_link 写入时落表(W1 未实施) | **需实施 W1 双链**(本范式的 cross-references 地基) |
| LLM agent 写入 | MCP 工具已有 documents create/update;89/89 现存文档均为 agent 创建 | 无差距(agent 写入是既成事实) |
| index.md | 无 | **后端生成 INDEX 视图**(Q3a:投影非页,零维护) |
| log.md | 无(评论/版本各有用途,不宜混用) | **不设**(Q3b;活动时间线由 versions/refs/comments 聚合兜底) |
| schema(CLAUDE.md/AGENTS.md) | 无项目级维护规则文档 | **Zeichen 不存**(Q4:通用块→use-zeichen skill,特有块团队自理) |
| qmd(长大后本地搜索:BM25/向量混合+LLM 重排,CLI+MCP 双形态) | search.query 整串 ILIKE、按更新时间排序、预览前 300 字截断;W2(pg_trgm 多词+相似度+片段)已裁定未实施 | **读平面主体:检索层与本范式同期落地(§3.5)** |
| raw/ 不可变来源 | **与场景冲突(§0 裁定)**:Zeichen 的 wiki 非源自原始文件;来源=过程本身——看板实体(需求/任务)、评论、事故、讨论、仓库提交 | 替代物=**过程事件流**;ref API(derives/documents/…)为挂接点(42 条活跃引用);附件降为补充输入 |
| lint | 断链检测:doc_link 落表后 SQL 可查;矛盾/孤儿/缺页:需 agent 读 | 已裁定(Q5):系统侧=断链+无 kind/summary;孤儿/过期/评分不做;语义 lint 归 skill |
| git 版本 | DocumentVersion 全量版本已有 | 无差距 |
| 人审 | 版本回滚+评论区已有;溯源标识已裁定(W4,未实施) | 已裁定(Q6=A):轻量——版本+评论+溯源即治理,无审核机制 |
| Obsidian 图视图 | 前端树形工作台 | 可选增强(P2) |

## 3. 系统设计(草案)

### 3.1 层次的 Zeichen 化(2026-10-07 修正:过程记录式,非编译式)

- **过程层(系统已有,触发源)**:看板(需求/任务)+ 评论 + 事故 + 提交——「what」
  的动态流。wiki 记录的对象与触发源;不可变语义=实体历史与版本可查。
- **wiki 层(静态知识层,LLM 维护结构)**:页面=现有 Document+frontmatter(D4:summary
  创作时写)。定位(用户 2026-10-07 完善):看板管动态(what is happening),wiki 收
  项目全部静态知识——为什么(decision/incident/preference)、怎么操作(howto)、
  规格是什么(spec)。**形态轴枚举已裁定(2026-10-07)**:decision / incident /
  preference / concept / entity / comparison / research / howto / spec 九类
  (doc_kind 存 frontmatter);讨论纪要不设(蒸馏进 decision/preference,否则留在
  评论区);枚举在 use-zeichen skill 中可扩展,系统不硬校验。
  人与 agent 写内容;agent(LLM)做结构维护:交叉引用与一致性(INDEX 由后端生成,
  LOG 不设,均无需 agent 维护)。
- **glossary 并入 wiki,统一叫 wiki(用户 2026-10-07 裁定)**:取消 wiki/glossary
  双模块。影响面(现状实测:词条 27、DIR 目录树、TERM-n 短码、aliases/定义语义、
  前端词条视图、MCP/API 的 doc_type 参数):doc_type 合一;词条成为普通 wiki 页
  (定义+aliases 进 frontmatter;TERM-n 短码按「永不改变」原则保留或映射,存量
  迁移方案实施时定);Directory 树并入 parent_id 树(目录变树节点);原「术语自动
  链接」降为渲染层可选功能(任意页 title/aliases 命中即提示,不再绑定词条模块)。
- **约定层(不在 Zeichen 内,2026-10-07 裁定)**:wiki 维护约定的通用块写在
  **use-zeichen skill**(按需加载,渐进披露);项目特有块各团队自理。Karpathy
  的「schema 使 LLM 成为有纪律的维护者」职能由该 skill 承担(计划一衔接点)。
- 附件/外部文章:降为补充输入(引用时贴入或挂附件),不构成独立一层。

### 3.2 三操作(全部在 agent 侧执行——后端零 LLM 纪律不变;操作指引属
use-zeichen skill 与团队自理约定,不进 Zeichen)

- **Record(记录,替代 Karpathy 的 ingest)**:触发=过程事件(任务收尾、需求变更、
  事故、重要讨论)或人/agent 主动;内容=把「why」写成页面(决策/复盘/偏好/概念);
  挂接=经 ref API 关联需求/任务(derives/documents);落页后 agent 做结构 bookkeeping
  ——联动更新相关概念页、补 [[双链]](doc_link 由后端写入时自动落表,D5)。
  **触发与分工:主动记录(Q1′ 裁定 B,2026-10-07)**——何时/为何记录由 agent harness
  决定,Zeichen 不设强制钩子;写法约定见 use-zeichen skill。
- **Query**(读路径,分层降级):① INDEX 命中 → ② 钻相关页(经 [[双链]]/反链扩展,
  摘要不足再读全文)→ ③ 带引用作答;INDEX 不覆盖(词没进目录/跨概念问题)→
  ④ 多关键词检索(pg_trgm,aliases 参与,命中片段返回)定位 → 回到 ②;有价值的答案
  回填 comparisons/ 新页(读反哺写)。
- **Lint**:系统侧只出**客观信号**(零 LLM 零维护):断链(保存时警告+清单)、
  **无 kind/无 summary(2026-10-07 暂定加入为明确信号**:INDEX 未分类节+缺 summary
  标注,兼作 skill 维护自检的工作清单)。**过期机制整体不做(2026-10-07 裁定,
  推翻旧 D6 的过期检测部分)**;**孤儿页信号不加**;质量评分类体检维持不做(D6)。
  语义 lint(矛盾/陈旧论断/缺页——含「依据的需求变了」这类语义判断)全部归
  use-zeichen skill 的「维护自检」,不进系统。

### 3.3 系统侧新增(最小集)

1. **doc_link + frontmatter 解析管线**(=原 W1,优先级提到最前:本范式地基);
2. **INDEX 生成器(后端投影,零维护)**:从 frontmatter 聚合——doc_kind 分节、每页
   一行(短码/标题/summary/更新时间)、未分类节兜底存量;经 API/MCP/导出面输出;
   检索结果同构(§3.5);
3. **(取消)SCHEMA 文档**——Q4 裁定 Zeichen 不存约定;通用块写在 use-zeichen
   skill,特有块团队自理(skill 编写属实施期,衔接计划一);
4. **glossary 合并迁移**:doc_type 合一;词条 27 篇转普通 wiki 页(aliases/定义进
   frontmatter,kind 由 agent 自行补标 concept);Directory 表零使用,直接废弃;
5. **lint 系统信号**:断链清单+无 kind/summary 清单(SQL/聚合级,零 LLM;
   孤儿页与过期机制均裁定不做);
6. 前端:INDEX 视图呈现(kind 分节,人读面);图视图 P2。

### 3.4 治理:多 agent 与人在环

- 溯源标识(W4 已裁定的部分)前置实施:页面/版本标注「哪个 agent、谁的主人」写的;
- **人在环:轻量(Q6 已裁定 A,2026-10-07)**——版本可回滚+评论+溯源即全部治理,
  不设审核/待审机制,与其他系统的交互完全平等;
- 项目边界即知识边界(现有权限模型不动)。

### 3.5 读平面:检索与导航(写是为了更好的读)

编译操作的产出物(INDEX、summary、双链、反链)本身就是读的基础设施;检索层补上
「导航走不通」的路径。**读路径分层降级,逐层加码 token 成本**:

```
R1 摘要层   frontmatter summary / 后端生成的 INDEX 视图(每页一行,kind 分节,零维护
           永真)—— 不开页即可判断相关性
R2 导航层   INDEX 视图 → [[双链]]/反链跟链 → 术语/aliases 消歧
R3 检索层   多关键词 pg_trgm(aliases 参与)→ 命中片段 → 定位到页 —— 兜底
             「不知道在哪个页/INDEX 没收录」的场景;支撑 lint 缺页检测
R4 全文层   干净 .md 全文(经 MCP/API);人类走前端富渲染
```

- **agent 读面**:MCP `docs.wiki.get` 返回 正文+frontmatter+双链+反链(一次调用
  拿到 R2+R4);`docs.search` 返回 R1+R3(摘要+片段+过滤,与 INDEX 行同构);
  INDEX 视图即 R1×全集。
- **人读面**:前端树形工作台(已有)+ 反链面板/术语悬浮(W1 前端部分)+ 图视图(P2,
  对应他「Obsidian graph view 看 wiki 形态」)。
- **读写闭环**:record 产出 R1/R2 的原料(summary/双链,INDEX 由后端从原料生成);
  lint 信号修复可读性(断链=断头路;无 kind/summary=目录盲区);query 的好答案
  回填=读产生写;回填的页又提升后续读的效率——系统价值随读写循环复利。
- 与旧 D7 的关系:wiki.context(预算组装)是读平面的**可选扩展**而非必需件;
  INDEX+跟链+关键词检索是本范式的标准读路径。

## 4. 裁定台账(Q1′–Q6 全部已关闭)

- **Q1 raw 层形态——已裁定(2026-10-07)**:raw 层与 Zeichen 场景冲突,不设;
  来源=过程事件流(§0/§3.1),附件为补充输入。
- **Q1′ 记录触发与分工——已裁定(2026-10-07):B 主动记录**。理由(用户):Zeichen
  只作为团队协作系统,不能强制要求用户记录;agent 什么时候记录、为什么记录是 agent
  harness 的范畴,与 Zeichen 无关。→ §0 边界原则;定期提炼(C)若发生也是 harness
 侧行为,不进系统范围。
- **Q2 分类方案(2026-10-07 修正定位)**。已裁定:① wiki 与 glossary **合并**,统一
  叫 wiki(§3.1);② **分类是核心需求**——「树近乎平铺(79/100 根级、嵌套 21、
  Directory 零使用)」是「系统从未提供分类机制」的结构性问题,不是不需要分类的
  证据;Karpathy 的 wiki 本身就有大量分类。问题不是「要不要分」,是「**如何分**」;
  ③ 约束:**领域大类定不准**(不可预设)。
  ④ **形态轴枚举已裁定(2026-10-07)**:decision/incident/preference/concept/
  entity/comparison/research/howto/spec + INDEX/LOG(research 为用户补充的漏项;
  howto/spec 用户裁定收进——wiki=静态知识层:why+how+spec)。
  ⑤ **树——已裁定(2026-10-07):保持现有自由文档树,不规定结构**。依据:Karpathy
  刻意不规定目录结构("The exact directory structure … will depend on your
  domain"),且其文件夹只作「默认归宿+人浏览」,agent 检索走 index+链接不经过目录。
  落到 Zeichen:parent_id 树机制不动、不设预设根(不设形态根也不设领域根);
  形态分类只走 frontmatter doc_kind;分类的可见面=INDEX 分节+双链+检索过滤;
  树怎么长由记录者与维护层自由决定(想分组就挂,不挂就根级平铺——与现状一致)。
  ⑥ **存量——已裁定(2026-10-07):Zeichen 侧不处理**。存量 wiki(~73 篇)保持
  无分类现状,不做批量标注/迁移分类;重新维护分类=各自 agent 的后续行为
  (harness 侧,遵循 §0 边界原则)。词条 27 篇并入后同样由 agent 自行标
  concept。影响:kind 过滤/INDEX 分节对存量暂缺,直至 agent 补标。
  **Q2 至此全部关闭**:①枚举九形态+保留页;②树=自由文档树不规定结构;
  ③存量系统不处理、agent 自行维护。
- **Q3a INDEX——已裁定(2026-10-07):系统动态生成**。用户理由:专业的东西由后端
  生成;分类(doc_kind)与摘要(summary)本来就是 wiki 页 frontmatter 里包含的东西,
  INDEX 由后端从中投影生成,**零额外维护**,不存为普通页。生成规则:按 doc_kind
  分节,每页一行(短码/标题/summary/更新时间);无 kind 存量页落「未分类」节,
  无 summary 回退开头截断(与 Q2⑥ 一致)。agent 的读路径不变:先读 INDEX 视图
  (API/MCP)→ 再钻页。
- **Q3a 附带裁定:检索结果采用同构**——search/docs.search 返回与 INDEX 同构的行
  (doc_kind 标注/分组 + summary/命中片段),读侧一种心智模型。
- **Q3b LOG——已裁定(2026-10-07):不设 LOG 页**(Karpathy 的 log.md 不移植,
  语义 log 页也不要)。活动时间线需要时由后端从 versions/refs/comments 聚合
  (零维护;是否单列聚合接口留实施定)。
- **Q4 SCHEMA——已裁定(2026-10-07,同日细化):Zeichen 不存 SCHEMA**。约定整体
  在系统外:通用块(九形态模板/frontmatter/链接约定/维护自检)**写在 use-zeichen
  skill 里**(用户细化:优于常驻系统提示词——skill 按需加载,即 Agent Skills 的
  渐进披露模式);项目特有块(什么值得记/tag 词表/命名保密规则)各团队自理,
  不在 Zeichen 负责范畴。多 agent 约定一致性由 skill 侧解决,Zeichen 只提供
  工具/信号/承载。use-zeichen skill 的编写属实施期工作(衔接计划一插件)。
- **Q5 lint 与 D6——已裁定(2026-10-07)**:系统侧客观信号=断链+无 kind/summary
  (暂定);**孤儿页信号不加**;**过期机制整体不做**(推翻旧 D6「过期检测进一期」,
  review_date 与 derives 联动两子机制均取消);质量评分维持不做(D6);语义 lint 归
  use-zeichen skill 维护自检节。
- **Q6 人在环强度——已裁定(2026-10-07):A 轻量默认**——版本+评论+溯源即治理,
  信任 agent,不设审核/待审机制;B/C 否决。

## 5. 与既有裁定(D1–D7 / W1–W4)的关系

| 旧裁定 | 在新范式下的状态 |
|---|---|
| D1/D2/D3 纯关键词 pg_trgm | **一等保留,与范式同期落地(P1)**:读平面 R3 层(§3.5)——Karpathy 范式在 wiki 长大后同样要加搜索(qmd);导航覆盖常用路径,检索覆盖「不知道在哪个页」,并支撑 lint 缺页检测 |
| D4 摘要创作时写 | **直接复用**:本范式正是「LLM 写摘要」,frontmatter summary=页头 |
| D5 双链写入时落表 | **升为最高优先**:cross-references 是编译层的核心结构 |
| D6 溯源+过期检测进一期/体检不做 | 溯源**保留前置**;**过期检测取消**(2026-10-07);体检维持不做(D6) |
| D7 wiki.context 三选一 | **搁置但不否定**:它是读平面的可选扩展(R3 之上的预算组装);本范式的标准读路径=INDEX+跟链+关键词检索,组装等语料与实测需要再议 |
| W1–W4 分期 | 重排:见 §6 |

## 6. 分期草案(方向确认后细化)

```
P0(地基)   doc_link+frontmatter 解析管线(原 W1)/ glossary 合并迁移 /
            溯源标识(页面与版本的 agent/人 标注)
P1(范式+读面) INDEX 生成器(后端投影,API/MCP/前端输出;检索结果同构)/
            lint 系统信号(断链+无 kind/summary)/
            读平面:pg_trgm 多词检索+命中片段(原 W2)/ docs.wiki.get 返回双链+反链
P2(增强)   图视图 / llms.txt 导出(原 W3 部分)/ wiki.context(D7 重议)/
            use-zeichen skill 编写(通用块:九形态模板+链接约定+维护自检;衔接计划一)
```

依赖:P0 无前置;P1 依赖 P0;P2 各自独立。

## 7. 风险与诚实边界

- **幻觉固化**(Karpathy 范式的已知批评,二手来源):记录把 LLM 的错误写成「事实」并
  沿链接传播。缓解:版本回滚、溯源标识(知道谁写的)、断链/kind 信号、skill 维护
  自检;治理按 Q6 轻量,人按需回滚。
- **多 agent 并发**:Karpathy 是单人单 agent;Zeichen 是多项目多 agent。同一页被并发
  更新时靠版本表(last-write+可回滚)兜底;不预设锁/待审(已裁定),出现实际问题再议。
- **token 成本**:record 联动更新多页在 MCP 侧是多工具调用循环,成本高于 Karpathy
  的纯文件 agent;联动节奏与批量上限在 use-zeichen skill 中约定。
- 现状数据(早间 61 篇/27 词条,晚间已 ~73/27;metadata 0、双链 0)意味着知识结构
  从零启动,无迁移包袱(存量分类 agent 自行渐进维护)。
