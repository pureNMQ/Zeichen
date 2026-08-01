# 02 cognee 能力与多主体记忆隔离

Status: open
Type: research
Blocked by:

## Question

调研 cognee(项目内已有本地安装 D:\Cognee 与 REST server,可查 README、源码、官方文档)并回答:
- REST API 全貌:remember / recall / improve / forget / datasets / sessions 的参数与限制
- 多主体(多 agent)记忆隔离用什么机制:per-agent dataset?per-agent session?cognee 是否支持多 dataset 写入与查询隔离
- 记忆条目能否挂自定义元数据(如 project_id / agent_id / 指向业务实体 id),供规格书设计"记忆↔业务实体互引"
- token 成本模型与批量写入(improve)的行为细节
- cognee 独立服务部署的关键配置(embedding 本地化、代理、数据集管理)

产出:事实清单 + 对"多 agent 记忆隔离"的可选方案评估,写入 research/cognee-capabilities 分支,链接回本 ticket。
