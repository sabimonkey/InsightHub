# 故障排查

先查看 `docker compose -f compose.release.yaml ps` 和服务日志。以下命令只读，不会删除数据。

## 页面打不开

```powershell
docker compose -f compose.release.yaml ps
docker compose -f compose.release.yaml logs --tail 200 frontend backend
Invoke-WebRequest http://localhost:8080/health
Invoke-WebRequest http://localhost:8080/ready
```

确认 `WEB_PORT` 与本机端口冲突情况。`/health` 检查服务存活；`/ready` 还要求数据库、Redis 与迁移就绪。

## 服务未健康或数据库未就绪

```powershell
docker compose -f compose.release.yaml logs --tail 200 postgres redis backend worker
docker compose -f compose.release.yaml ps
```

检查 `.env`、数据库健康状态和磁盘空间。迁移失败时，保留日志和卷并先备份；不要通过删除数据库卷来“修复”。

## RQ 任务不执行

检查 Backend/Worker 是否健康、Redis 是否就绪，以及 `worker` 日志中是否有队列订阅或 Job 异常。不要清空 Redis；其中可能有尚未处理的任务。

## 模型配置或请求失败

在设置页检查凭据来源、Provider 测试、Deployment 与工作流路由。API Key 不会在报告中明文显示。区分认证、模型权限、额度、网络、请求参数和结构化校验失败。修复配置后只对明确选择的资料重试，避免重复产生费用。

## 搜索没有语义结果

检查 Embedding 服务是否运行、容器是否能访问配置的 Base URL、模型名与向量维度是否匹配。缺少 Embedding 时关键词搜索仍可用。更换模型后不要把不同 profile 的向量混合；先评估受控回填。

## 安全的数据恢复

升级前备份 PostgreSQL 与 `app_data`。`docker compose down` 默认保留命名卷；**不要使用 `down --volumes`、`docker volume rm`、`docker system prune` 或数据库重置命令作为一般排障步骤**。确需恢复时先在隔离环境演练并确保备份可读。
