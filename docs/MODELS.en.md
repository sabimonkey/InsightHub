# AI models and embeddings

InsightHub treats generative models, embeddings, and image generation as three separate optional integrations. No model key is needed for first launch. Configure providers and workflow routes in **Settings**. Store credentials in the encrypted application vault; never put provider keys in `.env`, Compose files, or logs.

## Capability boundaries

| Capability | Use | When unconfigured |
|---|---|---|
| Chat / analysis | Source analysis, Ask, study notes, and other routed workflows | The corresponding AI operation is unavailable; collection and local persistence still work |
| Embeddings | Optional semantic vector retrieval | Keyword search remains available |
| Image generation | Optional knowledge-library covers | Extraction and analysis do not depend on covers |

The release registers ZAI (Zhipu GLM) for Chat and MiniMax `image-01` for images. Confirm available models, credentials, and routes in **Settings → AI Models** on the running instance. The release validation used Fake configuration and made no paid third-party model request.

## Optional BGE-M3

This project **does not bundle BGE-M3 weights or start an embedding server**. Operators obtain the model from the [BAAI/BGE-M3 model card](https://huggingface.co/BAAI/bge-m3) and select a compatible inference server. The model card identifies the model as MIT licensed; serving images, frameworks, and dependencies have their own upstream license terms.

The current InsightHub client consumes dense vectors:

- Configure the service API prefix as the base URL, for example `http://host.docker.internal:8011/v1`.
- InsightHub appends `/embeddings`; the effective request is `POST /v1/embeddings`.
- The request is OpenAI-style: `{"model":"BAAI/bge-m3","input":["..."]}`.
- Each result must provide a corresponding `data[].embedding` float array. The current application expects **1024 dimensions**.
- Optional `usage` is parsed. InsightHub does not request BGE sparse or ColBERT/multi-vector output.
- Both Backend and RQ Worker must reach the endpoint. For a service on the Docker host, use a container-reachable address rather than the container's own `127.0.0.1`.

Set `GENERIC_EMBEDDING_BASE_URL`, `GENERIC_EMBEDDING_MODEL=BAAI/bge-m3`, and `GENERIC_EMBEDDING_API_KEY` in `.env` as required by the server. The Generic provider-selection code requires a non-empty key even if the server itself has no authentication; do not mistake a placeholder for server-side authentication. For a local unauthenticated endpoint, restrict network access first and account for this provider-selection behavior when configuring it.

### Separate server and validation

Hugging Face [Text Embeddings Inference (TEI)](https://github.com/huggingface/text-embeddings-inference) is one option to evaluate; support varies by version, architecture, hardware, and model. The following is a connection example, **not a tested BGE server recipe**:

```text
GENERIC_EMBEDDING_BASE_URL=http://host.docker.internal:8011/v1
GENERIC_EMBEDDING_MODEL=BAAI/bge-m3
GENERIC_EMBEDDING_API_KEY=<manage locally for your deployment>
```

After starting a server, check its health endpoint, then call its OpenAI-compatible `/v1/embeddings` from a network location reachable by InsightHub. Verify result count matches input count and each vector has 1024 dimensions before a controlled index test. This docs upgrade did not download the multi-gigabyte weights or start TEI; CPU/GPU throughput, memory requirements, and server startup commands are therefore **unverified**. Follow the chosen server's official documentation and hardware/license requirements.

### Model changes and indexes

Embedding profiles are distinguished by provider, model, and dimension. Changing models does not convert existing vectors; vectors from different models must not be mixed. Review migration/backfill support and queue capacity before a controlled reindex. Keyword search remains available without embeddings.

## Data, cost, and security

- Cloud providers receive source content sent through their configured workflows. Review data classification and provider terms before enabling them.
- Third-party providers determine their own charges. An InsightHub local safety cap is not a provider quota balance.
- Do not copy API keys into shell history, screenshots, issues, or support logs.
- In production, expose only the Frontend entry point; keep embedding services reachable only on a trusted network.
