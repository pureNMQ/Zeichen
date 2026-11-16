# REQ:LLM Wiki 重构——**已在生产创建为 REQ-59**(2026-10-07,描述因单行/512 字符规范压缩,全文细节以设计稿为准)

> 目标项目:Zeichen(31a5c56c-0925-45f2-b370-6954b0de0348)
> 创建工具:requirements.create(project_id / title / description)
> 设计依据:research/zeichen-compiled-llm-wiki-design-20261007.md(定稿 v1,Q1′–Q6 全裁定)
> 调查依据:research/karpathy-llm-wiki-20261007.md、llm-knowledge-systems-landscape-20261007.md

---

## title(提交原文)

重构 wiki 为过程记录式 LLM 知识层——frontmatter 九形态、[[双链]]落表、glossary 合并、INDEX 后端投影、关键词读平面

## description(提交原文)

定位:看板=动态(what),wiki=静态知识层(why/how/spec),双读者为人与 Agent;范式参照 Karpathy LLM Wiki(知识持续积累、结构由 agent 维护、index-first 阅读),按 2026-10-07 设计定稿实施(research/zeichen-compiled-llm-wiki-design-20261007.md,Q1′–Q6 全裁定)。系统边界:Zeichen 只做承载与信号,不做强制记录、不存约定(通用约定由 use-zeichen skill 承载,另行处理)、零 LLM 依赖(REQ-57 纪律不变)。

本期范围(P0+P1):
1. frontmatter 解析管线:正文顶部可选 YAML(summary/doc_kind/tags/aliases);解析进现有 doc_metadata 列,get/list 结构化返回;doc_kind 九形态 decision/incident/preference/concept/entity/comparison/research/howto/spec(约定值,系统不硬校验);无 kind/无 summary 进 lint 信号清单。
2. [[双链]]写入时落表:支持 [[DOC-n]]/[[TERM-n]]/[[标题]]/[[标题|显示文本]]/[[标题#小节]];create/update/rollback 时解析落 doc_link 表(断链行保留:目标置空+原文);保存响应携带断链警告(不阻塞);详情返回正向链接+反向链接;前端渲染跳转、断链点击创建;#^ 块引用不做;标题/别名避开链接非法字符。
3. glossary 合并进 wiki,统一叫 wiki:doc_type 合一;存量 27 词条转普通 wiki 页(定义/aliases 进 frontmatter;kind 由 agent 自行渐进补标,系统不批量处理);DocumentDirectory 废弃(生产实测零使用);TERM-n 短码保留不断链;术语自动链接降为渲染层可选功能。
4. 溯源标识:页面/版本/列表/INDEX 标注创作主体(人名或 agent 名+其主人)。
5. INDEX 生成器(后端投影,零维护):从 frontmatter 聚合——doc_kind 分节、每页一行(短码/标题/summary/更新时间/溯源)、未分类节兜底存量、无 summary 回退开头截断;经 API/MCP/前端输出;检索结果与 INDEX 行同构(kind 标注+summary/命中片段)。
6. 关键词读平面:pg_trgm 扩展+GIN 索引(document.title/content);多关键词子串匹配+相似度排序(GIN 仅候选过滤,排序服务端计算;<2–3 字符关键词兜底走别名/短码精确或普通 LIKE;CJK trigram 行为上线前以真实语料 EXPLAIN 实测);命中片段返回替代现状前 300 字截断;aliases 参与匹配;新增 docs.search,升级 search.query。
7. MCP docs.wiki.get 增强:一次返回正文+frontmatter+双链+反链。

明确不做(本期及近端排除):向量/语义检索(旧 D1);孤儿页/过期(review_date 与 derives 联动)/质量评分类信号;LOG 页;SCHEMA 存 Zeichen;审核/待审机制;存量批量分类;树结构预设;wiki.context 组装接口(D7 搁置);附件内容检索;图视图与 llms.txt 导出(P2 另立)。

用户侧可观察结果:保存的 wiki 页带结构化元数据与正文双链(前端可点、断链可创建、反链可查);每个项目有一个自动生成、永不失真的知识 INDEX(按形态分节);检索支持多关键词并返回命中片段;词条与 wiki 统一为单模块;每个页面与版本可见创作主体(人/agent+主人)。
