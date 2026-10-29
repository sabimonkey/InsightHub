FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements-release.lock /app/requirements-release.lock
RUN python -m pip install --no-cache-dir -r /app/requirements-release.lock \
    && python -m playwright install --with-deps --only-shell chromium

COPY backend /app/backend
COPY prompts /app/prompts
COPY scripts /app/scripts
COPY docker/container-entrypoint.sh /usr/local/bin/insighthub-entrypoint
RUN chmod 0755 /usr/local/bin/insighthub-entrypoint

WORKDIR /app/backend
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/insighthub-entrypoint"]
CMD ["api"]
