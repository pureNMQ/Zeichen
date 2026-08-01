# 05 文档模块后端(版本链 + API schema)

Status: open
Type: task
Blocked by: 03

## Question

实现文档域后端(规格书 §3 的 document 实体与 §4 的 docs.* 工具,服务层):
- document CRUD + doc_type(wiki/glossary/api);content + metadata JSON(词条别名、API OpenAPI 子集 schema)
- 版本链:保存即新版本(document_version),保留最近 20 版,回滚=复制为新版本
- API schema 校验:端点冲突、字段类型合法性,保存即报错
- docs.* MCP 工具(约 15 个):wiki/glossary/api 三子域 + versions/rollback + api.references 反向引用自查
- 引用感知:改 schema 前返回反向引用警示列表
- pytest:版本链、schema 校验、回滚语义

产出:文档域完整后端 + MCP 工具。
