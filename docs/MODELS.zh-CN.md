# AI 模型与向量检索

InsightHub 将生成式模型、Embedding 和图像生成作为三类独立的可选外部能力。第一次启动不需要任何模型 Key；请在「设置」中管理 Provider 和工作流路由。凭据应通过 UI 保存到加密 Vault，不能写入 `.env`、Compose 文件或日志。

## 能力边界

| 能力 | 当前用途 | 没有配置时 |
|---|---|---|
| Chat / 分析 | 资料分析、问答、学习笔记等配置了模型路由的工作流 | 对应 AI 功能不可执行；收集与本地持久化仍可用 |
| Embedding | 可选语义向量检索 | 关键词检索仍可用 |
| 图像生成 | 可选知识库封面 | 正文提取和分析不依赖封面 |

发行代码注册 ZAI（智谱 GLM）Chat Provider 和 MiniMax `image-01` 图像 Provider。实际可用模型、凭据和路由应在当前实例的「设置 → AI 模型」确认。发布验证使用 Fake 配置，没有对第三方模型发起付费请求。

## BGE-M3（可选）

本项目**不打包 BGE-M3 权重，也不启动 Embedding 服务**。运维者需自行从 [BAAI/BGE-M3 官方模型卡](https://huggingface.co/BAAI/bge-m3)获取模型，并选择兼容的推理服务。模型卡标注 MIT；部署镜像、框架和依赖仍分别受其上游许可证约束。

当前 InsightHub 接口使用 dense 向量：

- Base URL 配置为服务 API 前缀，例如 `http://host.docker.internal:8011/v1`。
- InsightHub 在其后追加 `/embeddings`，所以实际请求为 `POST /v1/embeddings`。
- 请求结构为 OpenAI 风格 `{"model":"BAAI/bge-m3","input":["..."]}`。
- 每条结果必须包含与输入对应的 `data[].embedding` 浮点数组；应用当前期望维度为 **1024**。
- 可选 `usage` 会被读取。应用不请求 BGE sparse 或 ColBERT/multi-vector 输出。
- Backend 和 RQ Worker 都必须能访问服务；Docker 主机上的服务通常使用容器可达地址，而非容器内的 `127.0.0.1`。

在 `.env` 中设置 `GENERIC_EMBEDDING_BASE_URL`、`GENERIC_EMBEDDING_MODEL=BAAI/bge-m3`，并按服务认证要求设置 `GENERIC_EMBEDDING_API_KEY`。服务若不需要认证，项目 Provider 选择逻辑仍要求非空 Generic key 才启用该 Provider；不要把占位值误认为服务端认证。如果要对无认证端点联调，应先通过反向代理或网络 ACL 限制访问范围，并按代码实际 Provider 选择规则配置。

### 独立服务示例与验证

可以评估 Hugging Face [Text Embeddings Inference (TEI)](https://github.com/huggingface/text-embeddings-inference)，但不同版本、架构、硬件及模型支持会变化。以下只是连接参数示意，不是本项目已验证的 BGE 部署配方：

```text
GENERIC_EMBEDDING_BASE_URL=http://host.docker.internal:8011/v1
GENERIC_EMBEDDING_MODEL=BAAI/bge-m3
GENERIC_EMBEDDING_API_KEY=<由本地部署自行管理>
```

启动服务后先检查服务自身 health endpoint，再从 InsightHub 可达的网络位置请求其 OpenAI 兼容 `/v1/embeddings`，确认返回数量与输入数一致、向量维度为 1024，最后使用设置页的 Provider 测试/实际受控索引验证。本文升级验收未下载数 GB 权重，也未启动 TEI，因此 CPU/GPU 吞吐、内存占用和服务启动命令均为 **未验证**。请按所选服务官方文档、硬件及授权要求完成部署。

### 模型切换与索引

Embedding profile 按 Provider、模型和维度区分。换模型不会自动让旧向量变成新模型的向量；不同模型向量不可混用。检查迁移/回填能力和队列容量后，再对资料执行受控重索引。没有 Embedding 时，关键词搜索仍可使用。

## 数据、费用与安全

- 云端 Provider 会收到发往其工作流的资料内容；配置前确认数据分类与服务条款。
- 费用由第三方供应商计算，应用设置中的本地安全上限不是供应商剩余额度。
- 不要把 API Key 复制到命令历史、截图、Issue 或支持日志。
- 生产部署应只向 Frontend 暴露访问入口；Embedding 服务须仅在可信网络可达。
