#!/bin/sh
set -eu

cd /app/backend

case "${1:-api}" in
  api)
    python /app/scripts/bootstrap_release_db.py
    exec python -m uvicorn app.main:app --host "${INSIGHTHUB_API_HOST:-0.0.0.0}" --port "${INSIGHTHUB_API_PORT:-8090}"
    ;;
  worker)
    exec python -m rq.cli worker insighthub --url "${REDIS_URL:?REDIS_URL is required}" --worker-class rq.worker.SimpleWorker
    ;;
  *)
    echo "Usage: insighthub-entrypoint [api|worker]" >&2
    exit 64
    ;;
esac
