# InsightHub

InsightHub is a self-hosted research and learning workspace for collecting sources, extracting their content, analyzing evidence, and building a searchable personal knowledge base.

## Quick start

For a containerized installation, follow [English installation guide](docs/INSTALL.en.md) or [简体中文安装指南](docs/INSTALL.zh-CN.md). For Windows local installation, see [English local guide](docs/INSTALL-LOCAL.en.md) or [本机安装说明](docs/INSTALL-LOCAL.zh-CN.md). For contribution setup, see [development guide](docs/DEVELOPMENT.md).

The default container deployment keeps PostgreSQL, Redis, uploaded files, exports, and encrypted credentials in persistent volumes. Configure provider credentials in the application after first launch. Model keys are not included in this repository.

## Capabilities

- Collect URLs, text, and common document formats.
- Extract and preserve source content with provenance.
- Run evidence-oriented AI analysis through configured providers.
- Browse, search, and ask questions across saved research.
- Generate study notes and optional cover images.
- Keep original uploads and generated assets in local persistent storage.

## Requirements

- Docker Engine and Docker Compose v2 for the recommended installation.
- Alternatively, CPython 3.11.16 and Node.js 22 for Windows local installation.
- Optional: a separately hosted BGE-M3-compatible embedding endpoint. See the [model card](https://huggingface.co/BAAI/bge-m3) and deployment guide; model weights and the embedding server are external to this repository.

## License

InsightHub's project-authored code is licensed under **GNU AGPL-3.0-only**; see [LICENSE](LICENSE). You may use, modify, distribute, and use it commercially, subject to the license terms. In particular, distribution must retain the license and notices, and users interacting remotely with a modified version must be offered access to its corresponding source at no charge. Third-party components remain under their own licenses; review [third-party license notes](docs/THIRD-PARTY-LICENSES.md).

## Release

See [CHANGELOG.md](CHANGELOG.md) and [v1.0.0 release notes](docs/RELEASE-v1.0.0.md).
