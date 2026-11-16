# LLM Wiki 重构计划交接文件（2026-10-07）

> **交接范围**：计划二「LLM Wiki 系统改造」的完整讨论状态。接手人读完本文可直接续接讨论，
> 无需回放原始会话。计划一「DSH 插件代替 MCP」仅在 §8 交叉引用。
> **当前状态一句话**：设计草案 v2 已成文，七项决策已由用户裁定，两项待决
> （wiki.context 取舍、计划一小项），未定稿、未立项。

---

## 1. 计划来源与目标

用户于 2026-10-07 提出两个大计划：① 用 DSH 插件代替 MCP 接入；② 改造现有文档系统，
搭建完备的 LLM Wiki。本交接覆盖计划二。

目标：把现有 wiki/glossary 文档系统升级为**人类与 LLM 双读者**的知识库——检索更快更准、
文档之间成网、agent 能高效取用上下文。全部**原生实现**，不复活 Cognee（已于 REQ-57
因可靠性问题下线，教训是「外包整条 LLM 管线」，而非「不该做知识层」）。

流程裁定（用户）：**先出设计文档，审定后再入 Zeichen 立项**。目前处于「设计讨论」阶段。

## 2. 决策台账（已裁定，不可回退除非用户主动重开）

| # | 议题 | 裁定 | 用户理由/备注 | 日期 |
|---|---|---|---|---|
| D1 | 语义/向量检索 | **不做** | 「语义检索不可靠且会引入大量不相关文档；关键词检索最好，LLM 自己挑选的关键词比语义召回更精确」 | 10-07 |
| D2 | 向量存储 | 随 D1 取消 | 不引入 pgvector，**不换 postgres 镜像** | 10-07 |
| D3 | 分词/索引 | **pg_trgm 纯关键词** | 原稿 tsvector simple 已更正为错误方案（中文无空格分隔，simple 把整段中文当单 token，全文索引对中文失效）；pg_trgm 是自带 contrib，`CREATE EXTENSION` 即可，保持 ILIKE 子串语义 + GIN 索引加速 + 相似度排序 | 10-07 |
| D4 | 摘要来源 | **B 创作时写** | agent/人保存文档时在 frontmatter 自带 `summary:`；后端只解析返回、零 LLM 依赖；存量 61 篇回退开头截断（实测当前语料开头大多能传达主题，A 选项代价没有理论上的大） | 10-07 |
| D5 | 双链 | **做，写入时落表** | `[[DOC-n]]`/`[[标题]]`，create/update/rollback 时解析落 `doc_link` 表；反链查询、保存时断链警告、context 沿链扩展；存量零回填 | 10-07 |
| D6 | L4 一期范围 | **溯源标识 + 过期检测进一期；体检报告不做** | 前两者是「不错的功能」；体检报告「『好』的标准难制定且收益不大」 | 10-07 |
| — | 附件检索 | **不进** | 无「搜附件内容」实际场景记录，PDF 解析引入依赖 | 10-07 |

## 3. 待决事项（接手人第一优先级）

### 3.1 wiki.context 的取舍（三选一，讨论已充分）

背景：wiki.context = 服务端单次接口，多关键词检索 → 沿双链/引用扩展 → 段落级摘取 →
token 预算内组装返回，替代 agent「搜→拉全文→翻找→再搜」的多轮往返。

**关键转折**：用户深入研读 Cline 文章（见 §6 参考）后，此议题从「单项目 vs 跨项目」
扩展为「做不做」。Cline 哲学（agentic search：agent 自己带工具探索，反对服务端预组装）
对 wiki.context 构成直接挑战——其支付函数例子正是「组装逻辑漏掉没写关键词的自建框架」。

三条路线（已向用户完整摆开，等其拍板）：

| 路线 | 内容 | 特征 |
|---|---|---|
| 甲（Cline 式探索面） | 不做组装接口；磨利探索工具：`docs.wiki.get` 返回**双链+反链**（agent 顺着跟，等同 Cline 跟 import）、`search.query` 多关键词、文档树/llms.txt 索引 | agent 自判相关性；几乎全是 W1/W2 副产品，成本低 |
| 乙（做+单项目） | wiki.context 在单项目内组装；跨项目找线索先 `search.query`（本就跨项目）再切项目 | 边界清晰、链扩展完整 |
| 丙（做+跨项目） | 一次跨所有有权限项目组装 | 需标注来源项目+去重规则，链扩展跨项目部分失效 |

诚实评估（已告知用户）：61 篇语料下组装接口「合理但非必需」，分界线在几百篇；W3 排最后，
现在砍掉等文档多了再立项也完全合理。**注意：无论选哪条，W1/W2/D5 都照做**（两条路线都吃
双链表与关键词检索）。

### 3.2 计划一的三个小项（另一份交接的范围，此处仅记状态）

①GUI 配置入口（DSH 原生插件配置页 vs 面板自建表单）②attachment 工具保持 base64
③斜杠命令第一期不做——三项的利弊已摆开，等用户整体确认或逐项改。

## 4. 最新讨论进展（尚未合入设计稿，接手人定稿前需合入）

设计稿 [research/llm-wiki-system-design-20261007.md](llm-wiki-system-design-20261007.md)
当前为 v2/v3 混合状态（已合入 D1–D6 裁定与 pg_trgm 更正），**未合入**：

1. §3.1 的 wiki.context 三路线分析（含 Cline 哲学挑战与「不做」选项）
2. Cline 文章详解及其与用户检索立场的印证（见 §6）
3. 附件不进检索的正式裁定记录
4. W3 分期需按 §3.1 裁定结果重写（若选路线甲，W3 改为「探索面强化 + llms.txt 导出」）

## 5. 生产现状实测数据（2026-10-07，只读统计，接手可直接引用）

| 指标 | 值 |
|---|---|
| wiki 文档（未删） | 61 篇 |
| glossary 词条（未删） | 27 条 |
| metadata 非空的 wiki | **0 篇**（frontmatter 将是全新约定） |
| 正文含 `[[` 的文档 | **0 篇**（双链零迁移成本） |
| 平均/最长正文 | 3977 / 42215 字 |
| 文档创建者 | **89/89 全部为 agent**（溯源标识现在上线只会显示 agent） |
| 活跃实体引用 | 42 条：requirement→document 31、document→requirement 5、**document→document 2**、requirement→requirement 2、document→task 2 |
| `ref.create` 支持的组合 | requirement/task/document/repository/project 任意组合（doc↔doc 今天就合法） |
| 搜索现状 | 整串 ILIKE 子串匹配，按 updated_at 排序，"summary"=前 300 字硬截断 |
| pg 扩展 | plpgsql 已装；**pg_trgm 可用未启用**；pgvector 不可用（未装） |
| 文档标题唯一性 | 项目内唯一约束已存在（`_assert_document_title_unique`） |
| 短码稳定性 | DOC-n/TERM-n 复合主键，永不改变、不可复用（按码链接不会因改名断链） |

统计方式示例（只读、不违反生产纪律）：
`docker exec zeichen-postgres-1 psql -U zeichen -d zeichen -t -A -c "SELECT …"`

## 6. 关键参考（讨论中已核实原文）

- [Cline: Why Cline Doesn't Index Your Codebase](https://cline.ghost.io/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing/)（官方站 [cline.bot](https://cline.bot/blog/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing) 正文需 JS，用 Ghost 镜像）——三个反 RAG 论点（切块撕碎逻辑/索引腐烂/安全面翻倍）、「像开发者一样探索」、支付错误处理对照例。**与用户检索裁定完全同向**。
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)——「最小高信号 token 集」原则；子代理「大量探索→只返回 1–2k token 蒸馏结果」（wiki.context 的模式出处）；也点明预组装的代价（慢于预计算、组装逻辑漏了就是漏了）。
- [Cognition: DeepWiki](https://cognition.com/blog/deepwiki)——「给 LLM 吃的 wiki」产品形态实证（5 万+仓库）。
- [AnswerDotAI/llms-txt](https://github.com/AnswerDotAI/llms-txt)——llms.txt 标准（W3 导出面依据）。
- 诚实边界（已向用户申明）：实证的是**零件**（子代理压缩/agentic 关键词搜索/LLM 知识层），wiki.context 的具体接口形态是按本项目约束的组合，非照抄某产品。

## 7. 设计文档与环境索引

| 资产 | 位置 | 状态 |
|---|---|---|
| LLM Wiki 设计稿（本计划主文档） | `research/llm-wiki-system-design-20261007.md` | 草案 v2/v3，含决策进展表、四层能力模型（L1 结构/L2 检索/L3 组装/L4 协作）、pg_trgm 检索设计、doc_link 表结构、D4/D5 详述、分期 W1–W4 |
| DSH 插件设计稿（计划一） | `research/dsh-plugin-replace-mcp-design-20261007.md` | 草案，M1–M6 分期；与 W3 的插件暴露衔接 |
| LLM Wiki 一手调查汇总（2026-10-07 三路） | `research/llm-wiki-survey-20261007.md` | A 产品与格式 / B 检索哲学 / C 构建块核实 + D7 证据地图；两处技术假设修正（GIN 只过滤不排序、短中文词兜底） |
| LLM Wiki 架构文档（2026-10-07 重调研） | `research/llm-wiki-architecture-20261007.md` | 回答「如何搭建、需要哪些核心功能点」：15 类一手系统架构拆解、六域参考架构、F1–F22 核心功能点清单（P0/P1/P2）、Zeichen 映射 |
| LLM 知识系统全景（客观版） | `research/llm-knowledge-systems-landscape-20261007.md` | 九家族 × 六维做法矩阵、参数事实表、七分歧点；零项目映射 |
| Karpathy LLM Wiki 调查 | `research/karpathy-llm-wiki-20261007.md` + Gist 原文存档 `karpathy-llm-wiki-gist-20260404.md` | 一手 Gist 全文：LLM 编译维护 wiki 的范式（三层架构/三操作/index-first/Farzapedia）；用户所指「LLM wiki」的原始出处 |
| 仓库 | `/srv/zeichen`，develop 分支，ahead origin 85 commits | 勿自行 push/commit |
| 部署实例 | 本机 Docker Compose（zeichen-web/api/mcp/worker/postgres），API v0.3.0，公网 `https://www.mochigm.cn` | |
| 检索/文档相关代码 | `backend/app/services/documents.py`(965行)/`search.py`、`models/document.py`、`api/documents.py`、`mcp_server/tools.py`(875行)、前端 `frontend/src/pages/documents.tsx` | |

**本会话（或新会话）访问 Zeichen 的通路**：会话原生工具无 zeichen（本地 DSH 档案未装
mcp-zeichen；该条目只在远程主机 `~/.dsh/profiles/web/cordis.patch.yml`）。已验证可用通路：
bash（在远程主机执行）+ idle-runner 的 JSON-RPC 封装——
`sys.path.insert(0,'scripts/idle-runner'); import dispatch; url,headers=dispatch.load_mcp_endpoint(); dispatch.mcp_call(url,headers,tool,args)`
（凭据取自 `~/.zcode/cli/config.json`，agent 名 mocha，主人 pureNMQ，项目 Zeichen + Veyra 均
owner）。**写入必须先出草案经用户确认**（见 §9）。

## 8. 分期草案（按已定决策，W3 待 §3.1 裁定后可能改写）

```
W1  L1 结构层：frontmatter 规范与解析（含 summary）、[[双链]]写入时落表、
    术语自动链接、模板；溯源标识（无前置，可并入）
W2  L2 检索层：pg_trgm 扩展与索引、多词子串检索、相似度排序、命中片段、docs.search
W3  L3 组装层：wiki.context（或改「探索面强化」）＋ llms.txt / export.md 导出
    ＋（计划一 M2/M3 落地后）插件暴露 docs.search/context
W4  L4 协作层（一期内）：过期检测（review_date 标黄 + derives 依据需求变更提示，排 W1 后）
    ——体检报告已裁定不做
依赖：W1/W2 可并行；W3 依赖 W1+W2；溯源无前置可先行
```

## 9. 流程与纪律（接手必读）

1. **立项路径（用户已裁定「先设计后立项」）**：设计稿定稿 → 起草 REQ（先给用户看草案）
   → 经 §7 的 bash+MCP 通路在生产 Zeichen 创建 → 拆任务。生产实例 = Zeichen 项目本身。
2. **生产纪律**（AGENTS.md）：一切验证/测试禁止用真实账号（含管理员本人）；变更类操作用
   专用测试成员账号，用毕清理；agent 凭据须用户自建，禁止代建/复活账号、禁止绕过 API
   直写库签发凭据；只读诊断可用现有通路。
3. **写入前确认**：对 Zeichen 实体的创建/修改，先展示草案取得用户确认（用户已明确授权的
   具体写入除外）。
4. **用户沟通偏好（本讨论中明确表达）**：逐项讨论、一次一个议题；决策材料必须先讲「现状
   实测」再摆选项、不预设结论不诱导（曾批评「推荐」式提问）；解释概念要用系统内具体场景，
   忌抽象名词；提问卡片信息密度低，**重要决策材料用正文铺开**，用户文字回复。
5. 历史包袱：Cognee/记忆系统已下线（REQ-57，git 1bfd990 等 5 commits），讨论中**不要**再提
   恢复外部记忆产品。

## 10. 接手人行动清单

1. 读 `research/llm-wiki-system-design-20261007.md`（主文档）+ 本文件 §3 两个待决项
2. 向用户确认：wiki.context 三选一（§3.1，材料已备好可直接复述）＋ 计划一三小项（§3.2）
3. 按裁定合入设计稿（§4 列出的未合入项），重写 W3 分期
4. 请用户定稿；定稿后走 §9.1 立项流程
5. 实施顺序建议：溯源标识（最独立）→ W1 → W2 →（视裁定）W3 → W4；与计划一的衔接点在
   W3 的插件暴露（等计划一 M2/M3）
