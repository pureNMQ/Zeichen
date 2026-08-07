# Cognee 1.4.1 模型配置建议

本文只核对了 Cognee 1.4.1 的官方发布源码/模板；密钥不能提交到 Git。

## 推荐：DeepSeek 负责推理 + 本地 FastEmbed 负责向量

这是 Zeichen 当前本地开发最平衡的组合：`improve` 所需的结构化抽取、摘要由 DeepSeek 完成；向量不需要第二个云端密钥，也避免把 DeepSeek Key 误用于 Cognee 默认的 OpenAI embedding。Cognee 的配置模板明确说明：未设 `EMBEDDING_API_KEY` 时 embedding 会复用 `LLM_API_KEY`，而默认 embedding 是 OpenAI 的 `text-embedding-3-large`。[官方模板](https://github.com/topoteretes/cognee/blob/v1.4.1/.env.template#L13-L19) [embedding 配置源码](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/databases/vector/embeddings/config.py#L69-L112)

将下列变量保存到**项目根目录**的未跟踪 `.env`（`DEEPSEEK_API_KEY` 写真实密钥；下例直接把它给 Cognee 使用）：

```dotenv
LLM_PROVIDER=custom
LLM_MODEL=deepseek/deepseek-v4-flash
LLM_ENDPOINT=https://api.deepseek.com
LLM_API_KEY=替换为DeepSeek密钥

EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
```

DeepSeek 官方“Models & Pricing”当前列出的 OpenAI 格式模型标识为 `deepseek-v4-flash` 和 `deepseek-v4-pro`，基础地址为 `https://api.deepseek.com`。Cognee 将该值交给 LiteLLM，因此配置须使用 provider 前缀：`deepseek/deepseek-v4-flash`（或 `deepseek/deepseek-v4-pro`）；发送至 DeepSeek 的实际模型 ID 仍是官方列出的无前缀形式。[DeepSeek 官方模型与定价文档](https://api-docs.deepseek.com/quick_start/pricing)

Cognee 1.4.1 没有 `deepseek` 这个一等 provider；允许的通用 OpenAI 兼容入口是 `custom`，而 provider/model/endpoint/key 正是其 LLM 配置字段。[LLM 配置源码](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/llm/config.py#L20-L33) [官方模板的 custom 示例](https://github.com/topoteretes/cognee/blob/v1.4.1/.env.template#L367-L383)

`fastembed` 不需要 `EMBEDDING_API_KEY`，但首次使用会下载模型；如果想完全离线，应预先把模型缓存准备好。嵌入维度必须和模型一致，否则向量库第一次写入会发生形状不匹配；Cognee 源码在不能识别模型时会回退到 3072 维。[embedding 配置源码](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/databases/vector/embeddings/config.py#L13-L65)

## 纯本地：Ollama 同时承担 LLM 和 embedding

在宿主机安装并启动 Ollama、拉取聊天模型和 embedding 模型后，容器中使用：

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
LLM_ENDPOINT=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama

EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text:latest
EMBEDDING_ENDPOINT=http://host.docker.internal:11434/api/embed
EMBEDDING_DIMENSIONS=768
HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5

# 本地推理通常串行，保守限流；可按机器性能再提高
LLM_RATE_LIMIT_REQUESTS=10
LLM_RATE_LIMIT_INTERVAL=60
EMBEDDING_BATCH_SIZE=8
```

这组变量、端点形态、维度和 tokenizer 均来自 Cognee 1.4.1 官方 Ollama 示例。该版本会要求 Ollama 的 `LLM_MODEL`、`LLM_ENDPOINT`、`LLM_API_KEY` 三者同时存在；并对本地 provider 默认采用较低的 10 RPM 预算。[官方模板](https://github.com/topoteretes/cognee/blob/v1.4.1/.env.template#L353-L364) [Ollama 校验与限流源码](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/llm/config.py#L22-L46) [校验实现](https://github.com/topoteretes/cognee/blob/v1.4.1/cognee/infrastructure/llm/config.py#L198-L244)

## Docker 网络与应用配置

- Cognee 在容器内，`localhost:11434` 指向容器自身，不能指向 Windows 宿主机 Ollama；请用 `host.docker.internal:11434`。Cognee 官方 Compose 文件也用 `host.docker.internal:host-gateway` 将该主机名映射到宿主机。[官方 Compose](https://github.com/topoteretes/cognee/blob/v1.4.1/docker-compose.yml#L24-L28)
- 若 Ollama 也作为 Compose 服务加入同一个 network，则把两个 endpoint 改为 `http://ollama:11434/v1` 与 `http://ollama:11434/api/embed`；服务名是 Docker 内 DNS 名。
- **目前 Zeichen 的 `docker-compose.yml` 没有 `env_file`，且 LLM 配置只是注释，所以只创建根 `.env` 不会把变量传入 Cognee 容器。** 启动前需在 Compose 的 `cognee.environment` 显式加入所选变量（例如 `LLM_API_KEY: ${LLM_API_KEY:?}`），或加入 `env_file: .env`；然后运行 `docker compose up -d --force-recreate cognee`。仅重启不会让新环境变量生效。
- Zeichen 后端仍应保留 `COGNEE_BASE_URL=http://localhost:8000/api/v1`，这是**宿主机进程**访问已映射端口的地址；将来 API 也容器化并加入同一 Compose network 后，再改为 `http://cognee:8000/api/v1`。

除本地开发外，建议将 `LLM_API_KEY` 放入部署平台 secret，并同时替换 Cognee 的 `FASTAPI_USERS_JWT_SECRET`；官方模板明确标注默认 JWT secret 不适合生产。[官方模板安全段](https://github.com/topoteretes/cognee/blob/v1.4.1/.env.template#L222-L228)
