# Troubleshooting

Start with read-only health checks and logs. The commands below do not delete data.

## UI unavailable

```powershell
docker compose -f compose.release.yaml ps
docker compose -f compose.release.yaml logs --tail 200 frontend backend
Invoke-WebRequest http://localhost:8080/health
Invoke-WebRequest http://localhost:8080/ready
```

Check `WEB_PORT` and local port conflicts. `/health` checks liveness; `/ready` also requires the database, Redis, and schema migrations to be ready.

## Unhealthy service or database not ready

```powershell
docker compose -f compose.release.yaml logs --tail 200 postgres redis backend worker
docker compose -f compose.release.yaml ps
```

Check `.env`, database health, and free disk space. If migrations fail, retain logs and volumes and take a backup first; do not delete the database volume as a repair shortcut.

## RQ jobs are not running

Check Backend/Worker health, Redis readiness, and Worker logs for queue subscription or job errors. Do not clear Redis; it may contain pending work.

## Provider configuration or request failure

Inspect credential source, provider test, deployment, and workflow route in Settings. API keys are never shown in reports. Distinguish authentication, model access, quota, networking, request parameters, and structured-output validation failures. After correcting configuration, retry only explicitly selected sources to avoid duplicate charges.

## Search lacks semantic results

Check the embedding server, container reachability to the configured base URL, model ID, and vector dimensions. Keyword search remains available without embeddings. Do not mix vectors from different profiles after a model change; assess controlled reindexing first.

## Safe recovery

Back up PostgreSQL and `app_data` before upgrades. `docker compose down` preserves named volumes by default. **Do not use `down --volumes`, `docker volume rm`, `docker system prune`, or database-reset commands as routine troubleshooting.** Rehearse recovery in an isolated environment and verify backups before restoring.
