# v1.0.0 Documentation Upgrade Report

## Scope and safety

- Release snapshot base: `6f7b32a41a422c4f842b160c6dd83a8d8c47c8d7` (the local annotated `v1.0.0` release tag).
- Work was isolated in branch `codex/docs-upgrade-v1.0.0`; the original development checkout and snapshot `main` were not edited.
- No push, GitHub Release edit, or tag movement was performed. The public remote could not be rechecked from this run because DNS/network lookup failed; local publication evidence remains the prior release report and refs.
- No personal source data, screenshots, account identifiers, or API credentials were added. `.env.docs-validation` contains only a generated test password, is untracked/ignored, and is removed after test-stack cleanup.
- The tracked npm cache shipped in the base tag contains 515 cache files. A prior content scan found no provider/GitHub/npm/AWS keys, private-key headers, bearer credentials, or database-password URL patterns in those blobs. This docs branch removes those cache files from its new tree and adds ignore rules; it does not rewrite the public v1.0.0 tag/history.
- PyMuPDF 1.28.2 remains in the release dependency lock. The third-party license note already records the AGPL/commercial licensing question and the need for rights-holder/legal review; this documentation change does not purport to resolve it.

## Documentation delivered

- Expanded both README files with a first-launch checklist, bilingual document map, optional integrations and license information.
- Added bilingual provider/embedding, user, and troubleshooting guides.
- Expanded Chinese and English Compose install/deployment guides with Linux/macOS no-overwrite commands, health checks, configuration meanings, local-vs-provider quota distinction, and non-destructive recovery guidance.
- Added four editable Mermaid source diagrams and matching rendered Mermaid blocks to the architecture guide: service topology, ingestion-to-evidence, model/retrieval, and Docker topology.
- Added `scripts/check_docs.py` for local Markdown link/image target, code-fence, and declared configuration-name checks.
- Added seven current UI screenshots under `docs/assets/screenshots/`, captured from the isolated v1.0.0 Docker app. Provenance and synthetic-data limits are documented alongside them.

### Documentation references reviewed

- [REA](https://github.com/morluto/rea): clear top-level summary and direct documentation navigation.
- [Horizon](https://github.com/Thysrael/Horizon): staged quickstart and a concise “how it works” orientation.
- [BettaFish](https://github.com/666ghj/BettaFish): bilingual Docker setup and configuration guidance.

Only information hierarchy and navigation patterns were used; no wording, illustrations, or assets were copied.

## Verified implementation facts

- The Docker release runs five services: Nginx Frontend, FastAPI Backend, RQ Worker, PostgreSQL/pgvector, and Redis. Backend and Worker share `app_data` for persistent files and vault material.
- Docker first-run applies Alembic migrations before API start; Worker waits for API readiness. Startup cover generation is off in the template.
- The current embedding client appends `/embeddings` to the configured base URL, sends OpenAI-compatible `model` + `input`, reads dense `data[].embedding` vectors, and validates the active profile dimension of 1024. No sparse/ColBERT embedding path is wired into this app.
- BGE-M3 weights and an inference server are external optional services. The documented TEI connection values are examples only, not a tested full server recipe. No multi-gigabyte model was downloaded and no BGE endpoint was started in this task.
- Provider keys belong in the encrypted UI Vault. Model availability is governed by provider/deployment/workflow configuration, not by the docs or initial Docker startup.
- InsightHub cover budget settings are local safety controls; they do not report MiniMax official plan balances.

## Installation and runtime validation

| Check | Result |
|---|---|
| `docker compose ... config` with isolated synthetic environment | PASS |
| Release Docker Backend/Worker/Frontend image build | PASS; frontend build has the existing Vite chunk-size warning |
| Five-service isolated Compose startup | PASS; all five containers reported healthy |
| Alembic bootstrap | PASS; current revision `n0p1q2r3s4t5` |
| Frontend `/` via Nginx | HTTP 200 |
| `/health` via Nginx | HTTP 200 |
| `/ready` via Nginx | HTTP 200 |
| Synthetic UI text ingestion and extraction | PASS; one synthetic Source, one ContentChunk, one Fake embedding; no Claim/Analysis was created |
| Real model API / paid image call | NOT RUN; none was required or authorized for docs work |
| Standalone BGE-M3/TEI service and dense vector request | NOT RUN; weights were not downloaded |
| Full backend/frontend business test suite | NOT RUN in this docs-only branch; no application business code changed. The release snapshot's prior test status remains in `RELEASE-v1.0.0-REPORT.md` and is not represented as newly rerun. |

### Observed diagnostic limitations

The isolated Compose Worker container health check remained healthy and Worker logs showed it subscribed to the `insighthub` queue. However `GET /api/system` returned `worker: not_detected` after idle time, consistent with the app's RQ idle-worker heartbeat/process-detection path; `/ready` still returned 200. The same diagnostic reported `raw_storage: missing` because the empty demo used only text and no raw upload directory was created. These diagnostics were not changed as part of a docs-only scope. Operators should use the documented container/log checks and treat `/api/system` as a separate application diagnostic rather than infer that Docker health and API readiness are identical.

## Screenshots

- `docs/assets/screenshots/collection-synthetic.png`
- `docs/assets/screenshots/library-synthetic.png`
- `docs/assets/screenshots/search-synthetic.png`
- `docs/assets/screenshots/ask-synthetic.png`
- `docs/assets/screenshots/notes-synthetic.png`
- `docs/assets/screenshots/settings-synthetic.png`
- `docs/assets/screenshots/settings-models-synthetic.png`

They use the isolated synthetic Source `Synthetic demo note: A neighborhood library piloted a tool-lending shelf...`. No true model key was configured. Model settings show the Fake test provider and unconfigured cloud providers; the screenshot is not evidence of provider connectivity.

## Checks and remaining work

- `python scripts/check_docs.py`: PASS; 21 Markdown documents, zero broken local links/image targets, balanced fences, no undeclared environment names found against templates/config.
- Docker install/run and live HTTP health checks: PASS as described above.
- Isolated Compose stack and its three project-scoped test volumes were explicitly stopped and removed after screenshot capture; other Docker projects were not touched. The generated `.env.docs-validation` and override file were removed.
- Full app `verify.ps1`: NOT RUN. This branch changes documentation, ignore rules, and a screenshot helper only. It does not claim a full application regression pass.
- BGE-M3 actual serving: NOT RUN.
- PyMuPDF legal/rights-holder review: OPEN.
- `/api/system` idle-worker/raw-storage diagnostics: OBSERVED, not modified in this documentation task.
- Remote refs: NOT RECHECKED successfully due network/DNS availability; no remote mutation was attempted.

## Outcome

**PARTIAL** — bilingual docs, diagrams, live isolated Docker install/readiness, and synthetic browser screenshot evidence are complete. Full business `verify.ps1`, standalone BGE serving, legal review, and remote ref recheck remain unverified or external.

Final local commit: see the final report revision in the branch commit history.
