# 07 Wiki/字典/API 文档模块形态

Status: resolved
Type: grilling
Blocked by: 01

## Question

设计文档三子模块的形态(数据层面 01 已定:单一 document 实体 + doc_type,此处定各模块的行为与交互):
- Wiki:层级/自由页?页面版本历史?与需求/任务的互相引用
- 字典(glossary):词条结构(词名、定义、别名、所属项目?),谁维护,与 Wiki/文档的引用
- API 定义:结构化到什么程度(手写 Markdown vs 结构化 schema,如 OpenAPI 子集?);字段名改动后其他文档是否自动同步
- 编辑体验:Markdown 编辑器、实时预览是否 v1

产出:文档模块的实体形态与引用机制草案。

## Answer

- Wiki:自由页 + 可空 parent_id(显式层级兜底)+ reference 表互引,不搞强制目录树
- 版本:全文版本链,每次保存一版(保留最近 20 版),保存即发布(无草稿态);回滚 = 复制旧内容为新版本,历史永不覆盖
- 字典:词条项目级,统一 document 表(doc_type=glossary,正文=定义,metadata=别名列表);有编辑权者(含 agent)可维护;互引走 reference
- API 定义:OpenAPI 子集结构化 schema(端点/参数/请求响应体字段/错误码)存 metadata + Markdown 说明;保存时校验(端点冲突、字段类型);Web 端渲染;agent 读到结构化 schema
- 引用同步:引用感知 + 警示(改 schema 前显示反向引用),不自动同步
- 编辑体验:内容形态 = Markdown 文本(agent 原生输出,无转换层);Web 编辑器采用即时渲染(IR)模式所见即所得,不做双栏、不做富文本
