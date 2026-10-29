# 使用 Docker Compose 安装 InsightHub

这是推荐的单机部署方式，会运行 Web 前端、API、RQ Worker、带 pgvector 的 PostgreSQL 和 Redis。应用文件与凭据 Vault 主密钥保存在 Docker 持久化卷中。

## 环境要求

- Docker Engine 和 Compose v2 插件。
- 至少 4 GB 内存；处理 PDF 或图片时建议更多。
- 主机 8080 端口可用；如被占用，可修改 `WEB_PORT`。

## 安装

1. 下载或克隆发布源码并进入目录。
2. 创建私有环境文件，避免覆盖现有文件：

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.docker.example .env }
   ```

   Linux/macOS 可使用 `cp -n .env.docker.example .env`；若 `.env` 已存在，请保留并检查现有配置，不要覆盖。

3. 将 `POSTGRES_PASSWORD` 改成足够长的随机值。建议只使用十六进制字符，以便安全用于 Compose 生成的数据库连接 URL。保护好 `.env`。可在首次启动前设置 `INSIGHTHUB_CREDENTIALS_MASTER_KEY`；若留空，应用会在持久化目录中生成主密钥。请安全备份应用数据卷，否则丢失主密钥后将无法读取已加密的 Provider 凭据。
4. 启动服务：

   ```powershell
   docker compose -f compose.release.yaml up -d --build
   docker compose -f compose.release.yaml ps
   ```

5. 等待 Backend readiness 检查通过，然后打开 `http://localhost:8080`（或配置的 `WEB_PORT`）。首次启动不需要模型 Key；进入「设置」后再配置 AI Provider。

Backend 首次启动会先应用 Alembic 迁移，再启动 API。Worker 会等 API 就绪后启动。启动时自动生成封面已关闭，避免意外产生付费图片调用。配置和预算核对前，请勿开启付费功能。

首次安装会下载容器镜像和依赖，因此可能远超五分钟。后续检查可使用 `docker compose -f compose.release.yaml ps`、`Invoke-WebRequest http://localhost:8080/health` 和 `Invoke-WebRequest http://localhost:8080/ready`。配置项见[部署与运维](DEPLOYMENT.zh-CN.md)，模型与可选 Embedding 见[模型说明](MODELS.zh-CN.md)。

## Embedding

向量检索为可选功能。请从[官方模型卡](https://huggingface.co/BAAI/bge-m3)获取 `BAAI/bge-m3` 权重，并在独立管理的服务中运行；本仓库不包含模型权重或 Embedding 服务。在 `.env` 配置 `GENERIC_EMBEDDING_BASE_URL`、`GENERIC_EMBEDDING_MODEL=BAAI/bge-m3` 及该服务要求的 API Key。Backend 和 Worker 容器必须能够访问该地址。服务运行在 Docker 主机时，可使用 `http://host.docker.internal:8011/v1` 这类容器可访问地址；服务在同一 Docker 网络时，使用其服务 DNS 名称。接口必须兼容 OpenAI `POST <base-url>/embeddings` 并返回 1024 维向量。留空可禁用向量 Embedding；关键词搜索仍可使用。

## 更新与备份

升级前一起备份数据库和 `app_data` 卷。`app_data` 保存原始上传、派生文件、封面、导出文件及加密凭据 Vault 的主密钥。也请保留 PostgreSQL 与 Redis 卷。检查发布说明和迁移要求后，再更新源码并执行：

```powershell
docker compose -f compose.release.yaml up -d --build
```

## 停止与诊断

```powershell
docker compose -f compose.release.yaml logs --tail 200 backend worker
docker compose -f compose.release.yaml down
```

`down` 会保留命名卷。除非确定要删除本机数据库、队列、上传文件和加密凭据，否则不要添加 `--volumes`。`/health` 为存活检查，`/ready` 检查数据库、Redis 和 schema 是否就绪。

环境变量、安全边界和运维检查见[部署说明](DEPLOYMENT.zh-CN.md)。
