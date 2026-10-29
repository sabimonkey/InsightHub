# Install InsightHub with Docker Compose

This is the recommended single-host deployment. It runs the web application, API, RQ worker, PostgreSQL with pgvector, and Redis. All persistent application files and the credential-vault master key live in named Docker volumes.

## Requirements

- Docker Engine with the Compose v2 plugin.
- A host with at least 4 GB RAM; more is recommended when processing PDFs or images.
- A locally available port 8080 (change `WEB_PORT` if needed).

## Install

1. Download or clone the release source and enter its directory.
2. Create a private environment file without overwriting an existing one:

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.docker.example .env }
   ```

   On Linux/macOS, use `cp -n .env.docker.example .env`. If `.env` already exists, preserve it and review its values rather than replacing it.

3. Set `POSTGRES_PASSWORD` to a long random value. Use hexadecimal characters so the password can safely appear in the URL assembled by Compose. Keep `.env` private. Optionally set `INSIGHTHUB_CREDENTIALS_MASTER_KEY` before first launch; if omitted, the app creates one in persistent application storage. Back up that storage securely because losing the master key makes encrypted provider credentials unreadable.
4. Start the stack:

   ```powershell
   docker compose -f compose.release.yaml up -d --build
   docker compose -f compose.release.yaml ps
   ```

5. Wait for the backend readiness check, then open `http://localhost:8080` (or the configured `WEB_PORT`). Configure an AI provider from Settings. No model key is required for initial startup.

The first backend start applies Alembic migrations before starting the API. The worker starts only after the API is ready. Startup cover generation is disabled to prevent an unexpected paid image call. Do not enable optional paid features until their credentials and budgets are reviewed.

A first install downloads container images and dependencies and can take substantially longer than five minutes. For follow-up checks use `docker compose -f compose.release.yaml ps`, `curl http://localhost:8080/health`, and `curl http://localhost:8080/ready`. See the [deployment and operations guide](DEPLOYMENT.en.md) for settings and the [models guide](MODELS.en.md) for optional providers and embeddings.

## Embeddings

Vector search is optional. Obtain the `BAAI/bge-m3` weights from the [official model card](https://huggingface.co/BAAI/bge-m3) and run them in a separately managed service; this repository does not contain the weights or an embedding server. Configure `GENERIC_EMBEDDING_BASE_URL`, `GENERIC_EMBEDDING_MODEL=BAAI/bge-m3`, and that service's API key in `.env`. The backend and worker containers must be able to reach the service. For a service on the Docker host, use a host-reachable URL such as `http://host.docker.internal:8011/v1`; for a service on the same Docker network, use its service DNS name. The endpoint must implement OpenAI-compatible `POST <base-url>/embeddings` and return 1024-dimensional vectors. Leave the settings blank to disable vector embeddings; keyword search remains available.

## Updates and backups

Back up the database and the `app_data` volume together before upgrading. `app_data` contains original uploads, derived files, cover assets, exports, and the encrypted credential-vault key. Keep the PostgreSQL and Redis volumes as well. Review release notes and migration requirements before updating the source, then rebuild with `docker compose -f compose.release.yaml up -d --build`.

## Stop and diagnostics

```powershell
docker compose -f compose.release.yaml logs --tail 200 backend worker
docker compose -f compose.release.yaml down
```

`down` preserves named volumes. Do not add `--volumes` unless you intentionally want to erase the local database, queue, uploads, and encrypted credentials. Health endpoints are `/health` (liveness) and `/ready` (database/Redis/schema readiness).

For environment variables, security boundaries, and operational checks, see [deployment guide](DEPLOYMENT.en.md).
