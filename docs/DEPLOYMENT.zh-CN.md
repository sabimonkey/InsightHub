# 部署与运维

## 服务拓扑

`compose.release.yaml` 定义 PostgreSQL/pgvector、Redis、FastAPI Backend、RQ Worker 和 Nginx Frontend 五项服务。API 与 Worker 共用 `app_data` 卷，使加密凭据 Vault 和文件资产使用同一持久化目录。PostgreSQL 和 Redis 默认仅绑定回环地址；浏览器只应访问 Frontend。

## 环境变量与密钥

Compose 使用 `.env.docker.example` 作为模板，Compose 会自动读取 `.env`。不要提交 `.env`，也不要把 Provider API Key 写入 Compose 文件；请在应用凭据 Vault 中配置。保护 Docker 数据卷备份和可选的 `INSIGHTHUB_CREDENTIALS_MASTER_KEY`。若提供主密钥，Backend 与 Worker 重启时必须使用相同值；若留空，应用生成的密钥保存在 app data 中，两项服务都挂载该卷。

在使用服务前设置高强度数据库密码。PostgreSQL 和 Redis 默认绑定 `127.0.0.1`。远程访问应通过可信反向代理配置 TLS 和访问控制；不要将开发数据库或 Redis 暴露到公网。

Docker 模板中的变量：

| 变量 | 用途 |
|---|---|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PostgreSQL 初始化账户；密码不得提交 |
| `COMPOSE_PROJECT_NAME` | Compose 项目标识，多个实例应使用不同名称 |
| `WEB_PORT` | Frontend 对主机开放的 HTTP 端口 |
| `POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` | 绑定到回环地址的诊断端口 |
| `INSIGHTHUB_CREDENTIALS_MASTER_KEY` | 可选 Vault 主密钥；Backend/Worker 必须一致 |
| `GENERIC_EMBEDDING_BASE_URL` / `GENERIC_EMBEDDING_MODEL` / `GENERIC_EMBEDDING_API_KEY` | 可选 OpenAI 兼容向量服务；留空禁用 |
| `COVER_AUTO_ENABLED` / `COVER_AUTO_STARTUP_SCAN_ENABLED` | 自动封面开关；模板中默认关闭 |
| `COVER_MONTHLY_BUDGET` | InsightHub 本地封面尝试安全上限，不是 MiniMax 官方额度 |

完整配置示例见根目录 `.env.docker.example`。业务 Provider API Key 应在 UI 的加密 Vault 配置，不应放入 Compose 环境。

容器会在 `/LICENSE` 提供当前发布版本的许可证原文。分发镜像时，应同时提供对应版本的完整源代码快照，包括构建、安装、运行脚本和锁定依赖文件；在运行修改后的网络服务前，应在部署说明中提供该版本的公开源码地址。

## 付费集成

默认关闭启动时的封面生成。`COVER_AUTO_STARTUP_SCAN_ENABLED=false` 可防止启动时安排配图任务。配置凭据并检查应用内安全预算后，再决定是否开启自动配图。模型 API 可能产生费用；首次启动不会发起付费调用。

## 持久化与恢复

命名卷：

- `postgres_data`：关系型记录和 pgvector 数据。
- `redis_data`：Redis AOF 与排队任务。
- `app_data`：原始/派生文件、封面、导出、备份及凭据 Vault 密钥材料。

应将数据库与 `app_data` 协同备份。只恢复其中一项可能导致记录缺少文件，或凭据无法解密。Redis 队列属于运行状态；维护时应先检查队列并让 Worker 正常退出。依赖恢复流程前，应先在独立环境进行完整恢复演练。

## 健康检查与故障排查

- `GET /health`：API 存活状态。
- `GET /ready`：数据库、Redis 和迁移就绪状态。
- `docker compose -f compose.release.yaml ps`：服务健康状态。
- `docker compose -f compose.release.yaml logs --tail 200 backend worker`：API 与 Worker 日志。

Worker 健康检查要求至少有一个已注册的 RQ Worker。若持续不健康，请检查日志、`REDIS_URL` 和 `insighthub` 队列。排查前不要直接删除 Redis 数据，应先审计排队任务。

更多无损检查步骤见[故障排查](TROUBLESHOOTING.zh-CN.md)。

## BGE-M3 边界

BGE-M3 是可选外部服务。请从[官方模型卡](https://huggingface.co/BAAI/bge-m3)获取权重，在独立服务中运行，并在 `.env` 配置 `GENERIC_EMBEDDING_BASE_URL`、`GENERIC_EMBEDDING_MODEL` 和服务 API Key。Backend 与 Worker 容器必须能访问该服务；接口需兼容 OpenAI `POST /embeddings` 并返回 1024 维向量。本部署不管理或打包模型权重及服务，不要将大体积权重复制进仓库或容器镜像。

## 升级

阅读发布说明并备份全部持久化数据后，再更新源码并重建。Backend 启动时应用 Alembic 迁移。升级验证完成前保留可恢复备份。不要对生产数据库运行会清理数据的验证脚本。
