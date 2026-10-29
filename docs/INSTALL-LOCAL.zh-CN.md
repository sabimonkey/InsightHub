# Windows 本机安装

适用于 Windows 主机已经运行 PostgreSQL/pgvector 与 Redis 的场景。需要一体化部署时，请使用 [Docker Compose 安装](INSTALL.zh-CN.md)。

## 环境要求

- Windows 10/11 x64。
- CPython 3.11.16 x64（发布锁文件以此运行时完成验证）；项目元数据不支持 Python 3.12。
- Node.js 22 和 npm。
- PostgreSQL 17，启用 `vector` 扩展；默认监听 `127.0.0.1:15434`。
- Redis 7；默认监听 `127.0.0.1:16380`。
- Playwright Chromium，用于浏览器渲染提取回退。

## 安装

1. 下载或克隆发布源码，在仓库根目录打开 PowerShell。
2. 仅在 `.env` 不存在时从模板创建：

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.local.example .env }
   ```

   设置 `POSTGRES_PASSWORD` 与 `DATABASE_URL`，确保它们对应本机 PostgreSQL 账户。保护好 `.env`。首次启动时保持 Provider Key 为空，之后可在「设置」中配置。默认关闭封面自动生成。

3. 创建虚拟环境并安装固定版本的 Backend 依赖：

   ```powershell
   py -3.11 -m venv .venv
   $version = & .\.venv\Scripts\python.exe -c "import platform; print(platform.python_version())"
   if ($version -ne "3.11.16") { throw "发布依赖锁已用 CPython 3.11.16 x64 验证；当前为 $version。请安装该版本解释器并重新创建 .venv。" }
   .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r .\backend\requirements-release.lock
   .\.venv\Scripts\python.exe -m playwright install chromium
   ```

4. 安装前端依赖并应用数据库迁移：

   ```powershell
   Push-Location frontend
   npm ci
   Pop-Location
   .\.venv\Scripts\python.exe .\scripts\bootstrap_release_db.py
   ```

5. 启动项目管理的 API、Worker 和前端：

   ```powershell
   .\scripts\start.ps1
   .\scripts\manage.ps1 status
   ```

   打开 `http://127.0.0.1:5174`。只使用 `scripts\stop.ps1` 停止本项目管理的服务。

运行脚本优先使用 `.venv\Scripts\python.exe`。只有明确选择其他 Python 3.11 解释器时才设置 `INSIGHTHUB_PYTHON`。锁文件固定 Python 包，不包含 PostgreSQL、Redis、Chromium、Node.js 或 BGE-M3 权重；BGE-M3 仍是可选外部服务。

## 可选 BGE-M3 Embedding

从[官方模型卡](https://huggingface.co/BAAI/bge-m3)获取 `BAAI/bge-m3`，并使用单独管理的 OpenAI 兼容 Embedding 服务运行。在 `.env` 设置 `LOCAL_EMBEDDING_BASE_URL`（例如 `http://127.0.0.1:8011/v1`）和 `LOCAL_EMBEDDING_MODEL=BAAI/bge-m3`；服务需支持 `POST <base-url>/embeddings` 并返回 1024 维向量。仓库不包含服务或权重。未配置服务时，关键词搜索仍可使用，向量检索不可用。

不要把生产数据库用于测试。隔离测试环境和命令见[开发环境说明](DEVELOPMENT.md)。
