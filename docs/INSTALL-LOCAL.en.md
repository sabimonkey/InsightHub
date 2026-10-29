# Local Windows installation

Use this option when PostgreSQL/pgvector and Redis are already available on the Windows host. For a self-contained deployment, use [Docker Compose](INSTALL.en.md).

## Requirements

- Windows 10/11 x64.
- CPython 3.11.16 x64 (the release lock was validated with this runtime); Python 3.12 is not supported by the project metadata.
- Node.js 22 and npm.
- PostgreSQL 17 with the `vector` extension, listening on `127.0.0.1:15434` by default.
- Redis 7, listening on `127.0.0.1:16380` by default.
- Playwright Chromium for browser-rendered extraction fallback.

## Install

1. Download or clone the release source and open PowerShell in the repository root.
2. Create `.env` without replacing an existing file:

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.local.example .env }
   ```

   Set `POSTGRES_PASSWORD` and `DATABASE_URL` to match your local PostgreSQL account. Keep `.env` private. Leave provider keys blank during initial setup; configure them later in Settings. Cover generation is disabled by default.

3. Create a virtual environment and install the pinned backend dependencies:

   ```powershell
   py -3.11 -m venv .venv
   $version = & .\.venv\Scripts\python.exe -c "import platform; print(platform.python_version())"
   if ($version -ne "3.11.16") { throw "This release lock was validated with CPython 3.11.16 x64; found $version. Install that interpreter and recreate .venv." }
   .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r .\backend\requirements-release.lock
   .\.venv\Scripts\python.exe -m playwright install chromium
   ```

4. Install the frontend dependencies and apply database migrations:

   ```powershell
   Push-Location frontend
   npm ci
   Pop-Location
   .\.venv\Scripts\python.exe .\scripts\bootstrap_release_db.py
   ```

5. Start the project-managed API, worker, and frontend:

   ```powershell
   .\scripts\start.ps1
   .\scripts\manage.ps1 status
   ```

   Open `http://127.0.0.1:5174`. Stop only the services managed by this project with `scripts\stop.ps1`.

The runtime scripts prefer `.venv\Scripts\python.exe`; set `INSIGHTHUB_PYTHON` only when deliberately selecting another Python 3.11 interpreter. The lock pins Python packages but does not bundle PostgreSQL, Redis, Chromium, Node.js, or BGE-M3 weights. BGE-M3 remains an optional external service.

## Optional BGE-M3 embeddings

Download `BAAI/bge-m3` from the [official model card](https://huggingface.co/BAAI/bge-m3) and run it using a separately managed OpenAI-compatible embeddings server. Set `LOCAL_EMBEDDING_BASE_URL` (for example `http://127.0.0.1:8011/v1`) and `LOCAL_EMBEDDING_MODEL=BAAI/bge-m3` in `.env`; the endpoint must support `POST <base-url>/embeddings` and return 1024-dimensional vectors. The server and weights are not included. Without this service, keyword search remains available and vector search is disabled.

Do not use a production database for tests. Read [development setup](DEVELOPMENT.md) for isolated test configuration and commands.
