# 07 Wiki/字典/API 文档模块形态

Status: open
Type: grilling
Blocked by: 01

## Question

设计文档三子模块的形态(数据层面 01 已定:单一 document 实体 + doc_type,此处定各模块的行为与交互):
- Wiki:层级/自由页?页面版本历史?与需求/任务的互相引用
- 字典(glossary):词条结构(词名、定义、别名、所属项目?),谁维护,与 Wiki/文档的引用
- API 定义:结构化到什么程度(手写 Markdown vs 结构化 schema,如 OpenAPI 子集?);字段名改动后其他文档是否自动同步
- 编辑体验:Markdown 编辑器、实时预览是否 v1

产出:文档模块的实体形态与引用机制草案。
