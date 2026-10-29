# Local development setup

## Prerequisites

- CPython 3.11.16 x64 (the release dependency lock was validated with this runtime).
- Node.js 22 and npm.
- PostgreSQL 17 with pgvector and Redis 7, either from the repository's development Compose setup or an existing local installation.

## Environment

Create a development-only environment file from `.env.local.example` if `.env` does not already exist. Set a strong database password and make `DATABASE_URL` match it. Keep `.env` untracked. Do not reuse a production database for tests.

Install the pinned Python and frontend dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements-release.lock
.\.venv\Scripts\python.exe -m playwright install chromium
Push-Location frontend
npm ci
Pop-Location
```

Prepare the database with `python scripts\bootstrap_release_db.py`, then use the project scripts to start the API, worker, and frontend. The release bootstrap handles the initial provider seed required by the current migration chain and is safe to repeat; it does not replace existing provider routes. From the repository root, `scripts\start.ps1` starts the local development stack; `scripts\stop.ps1` stops only project-managed services. Open `http://127.0.0.1:5174`.

Use a separate database and isolated `AUTOMATION_TEST` data for tests. The root `docker-compose.yml` is intended for local development and is separate from the release deployment in `compose.release.yaml`.
