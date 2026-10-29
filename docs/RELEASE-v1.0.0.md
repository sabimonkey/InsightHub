# InsightHub v1.0.0

InsightHub v1.0.0 packages the self-hosted application for reproducible installation with Docker Compose.

## Included

- React/Vite frontend served by Nginx.
- FastAPI backend and RQ worker.
- PostgreSQL 17 with pgvector and Redis 7.
- Persistent Docker volumes for database, queue, files, covers, and encrypted credential-vault material.
- English and Simplified Chinese installation and deployment documentation.
- Optional external BGE-M3 embedding service integration; model weights are not distributed.

## First launch and security

No AI provider credential is bundled. Configure credentials through the application after startup. Automatic cover scanning at startup is disabled by default. Before deployment, set a strong database password, protect `.env`, and back up PostgreSQL together with application data and the credential-vault master key.

See [installation](INSTALL.en.md), [中文安装](INSTALL.zh-CN.md), and [deployment guide](DEPLOYMENT.en.md).

## License

InsightHub-authored code is licensed under GNU AGPL-3.0-only. Third-party software keeps its own license terms; review [third-party license notes](THIRD-PARTY-LICENSES.md). The container serves the full license text at `/LICENSE`. Do not distribute a modified image without also providing a compliant corresponding-source offer for the exact version.
