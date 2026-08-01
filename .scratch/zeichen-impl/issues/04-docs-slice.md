# 04 文档闭环(后端版本链 + MCP + Web IR 编辑器)

Status: open
Type: task
Blocked by: 03

## Question

实现文档域完整闭环(规格书 §3 document 实体 + §4 docs.* 工具 + §7 页面/§7.3 IR 编辑器):
- 后端:document CRUD + doc_type(wiki/glossary/api)、版本链(保存即版本,最近 20 版,回滚=新版本)、API schema 校验(端点冲突/字段类型)、引用感知(改 schema 前返回反向引用警示)
- MCP:docs.wiki.* / docs.glossary.* / docs.api.* 工具(~15 个,含 versions/rollback/api.references)
- Web:Wiki 阅读/编辑(IR 编辑器——Milkdown/Bisheng 在此验选型)/版本历史/回滚、字典列表/词条页、API 列表/详情(schema 渲染+编辑+反向引用)
- 测试:后端版本链/schema 校验/回滚语义;前端 IR 编辑器渲染/回滚交互

产出:Wiki/字典/API 三子模块可用闭环,agent 能读写文档、人类能 IR 编辑。
