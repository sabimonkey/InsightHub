# Deployment and operations

## Service topology

`compose.release.yaml` defines five services: PostgreSQL/pgvector, Redis, FastAPI backend, RQ worker, and Nginx frontend. API and worker share the same `app_data` volume so the encrypted credential vault and file assets resolve to the same persistent store. PostgreSQL and Redis are published only on loopback by default. The frontend is the only service intended for browser access.

## Environment and secrets

The Compose file uses `.env.docker.example` as a template; Compose reads `.env` automatically. Do not commit `.env` or place provider API keys in Compose files. Configure provider keys in the application credential vault. Protect Docker volume backups and the optional `INSIGHTHUB_CREDENTIALS_MASTER_KEY` as secrets. If a master key is supplied, keep the same value across API and worker restarts. If it is omitted, the application-generated key is stored with app data and both services mount that volume.

Set a strong database password before exposing or using the stack. PostgreSQL and Redis ports bind to `127.0.0.1` unless deliberately changed. Put TLS and remote access controls in a trusted reverse proxy; do not expose the development database or Redis publicly.

The container serves the exact release license at `/LICENSE`. Keep the corresponding source snapshot, including build/install/run scripts and lock files, available alongside any image distribution; publish the repository URL in the deployment instructions before operating a modified network-facing release.

## Paid integrations

Cover generation is disabled at startup by default. `COVER_AUTO_STARTUP_SCAN_ENABLED=false` prevents startup from scheduling cover runs. Configure provider credentials and review the in-app safety budget before enabling automatic cover generation. Model APIs may incur charges; this deployment does not make paid calls during initial startup.

## Persistence and recovery

Named volumes:

- `postgres_data`: relational records and pgvector data.
- `redis_data`: Redis AOF and queued jobs.
- `app_data`: original/derived files, covers, exports, backups, and credential-vault key material.

Back up the database consistently with `app_data`; preserving only one may leave records without assets or credentials that cannot be decrypted. The Redis queue is operational state. Plan maintenance with workers stopped gracefully and inspect queue state first. A full restore runbook should be tested against a separate stack before relying on it.

## Health and troubleshooting

- `GET /health`: API liveness.
- `GET /ready`: database, Redis, and migration readiness.
- `docker compose -f compose.release.yaml ps`: health state.
- `docker compose -f compose.release.yaml logs --tail 200 backend worker`: API and worker logs.

The worker health check requires at least one registered RQ worker. If it stays unhealthy, inspect its logs and confirm `REDIS_URL` and the `insighthub` queue. Do not delete Redis data to recover a worker without first auditing queued jobs.

## BGE-M3 boundary

BGE-M3 is optional and external. Obtain weights from the [official model card](https://huggingface.co/BAAI/bge-m3), run the model in a separately managed compatible service, and set `GENERIC_EMBEDDING_BASE_URL`, `GENERIC_EMBEDDING_MODEL`, and the service API key in `.env`. Backend and worker containers need network access to the endpoint, which must implement OpenAI-compatible `POST /embeddings` and return 1024-dimensional vectors. The weights, server, and server lifecycle are outside this deployment; they are not copied into the repository or default images.

## Upgrades

Read the release notes, back up all persistent data, then update the release source and rebuild. Backend startup applies Alembic migrations. Keep a recoverable database and app-data backup until the upgraded instance is verified. Do not run destructive verification scripts against a live database.
