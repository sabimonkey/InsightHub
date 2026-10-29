# InsightHub v1.0.0 release qualification report

## Status

**QUALIFIED FOR PUBLICATION.** The sole target is the owner-created public repository `https://github.com/sabimonkey/InsightHub`; the intended release page is `https://github.com/sabimonkey/InsightHub/releases/tag/v1.0.0`. This report is part of the sanitized release tree. A fresh single-root commit and tag are finalized only after this report and the final scan are committed. The stale tag in the private snapshot is not included.

## Snapshot and ownership review

- Source worktree baseline: `530b031bbf9718fdf311d9b54788f899f82ba0ef` on `main`; pre-existing dirty files were left untouched.
- Private snapshot baseline: `b04feafb81819aaaff7998dab90240a4c57589be`. Sanitized documentation commits: `83d5047a6e16420ac0a13242da0f599986b236bf`, `716f7d2ada60b8943507d97e8e0e877e859f1037`, and `1ee0a52adce06aaacd24502300ce0e6a4e44f9c2`. The old local `v1.0.0` tag targets `676aaa4033fb015e0bec6904441a2569ae939ac9` and will not be pushed.
- The release Git tree contains no production database, user application data, screenshots, model weights, or runtime logs. Its single generic commit identity and lack of copyright headers do not independently establish legal ownership; the owner selected AGPL-3.0-only for InsightHub-authored code.
- The public history is deliberately flattened to a fresh single root commit. The source/private history (which contained fake key-shaped test fixtures) is not reachable from the public branch or tag. The release commit uses a project-level author identity instead of the workstation's personal Git email.

## License and third-party review

- Replaced root `LICENSE` with the complete, unmodified GNU AGPL v3 text from the official GNU source: <https://ftp.gnu.org/pub/gnu/Licenses/agpl-3.0.txt>.
- Updated English and Simplified Chinese README and release notes to explain AGPL-3.0-only, permitted use/modification/distribution/commercial use, and relevant license/source obligations.
- Updated `docs/THIRD-PARTY-LICENSES.md`. PyMuPDF 1.28.2 is pinned and used by PDF extraction/export; PyMuPDF4LLM is absent from the release lock. Third-party packages retain their own terms. This is not a complete SBOM or legal opinion.
- The frontend image serves the exact license at `/LICENSE`; HTTP smoke check returned 200 and 34,427 bytes. The candidate UI links the exact release source at the supplied public repository's `v1.0.0` tag; the link will resolve after the tag is created.
- `exporting.py` uses PyMuPDF without setting PDF metadata. A direct PyMuPDF 1.28.2 smoke-generated PDF had empty Producer/Creator/Title metadata; the app export path was inspected, not integration-executed. Official PyMuPDF docs describe these metadata fields but the reviewed docs do not state that generated PDFs must include PyMuPDF producer/copyright metadata. Preserve package notices in the software distribution; do not add an unverified or misleading attribution to user PDFs. This review is not legal advice; obtain Artifex clarification if the output attribution scope remains uncertain. [Exact PyMuPDF 1.28.2 release](https://github.com/pymupdf/PyMuPDF/releases/tag/1.28.2), [licensing page](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright), [metadata docs](https://pymupdf.readthedocs.io/en/latest/document.html#Document.metadata).

## Secrets and personal-data audit

- Audited 983 tracked snapshot paths/text files. No real provider credentials, private keys, personal email addresses, Windows account paths, database dumps, uploaded documents, image assets, or model weights were found.
- The only `.env` paths are `.env.docker.example` and `.env.local.example` templates; no actual `.env` is tracked.
- Replaced key-shaped fake `sk-...` test values with non-key-shaped placeholders in seven test files and adjusted one redaction fixture. The original source worktree was not modified.
- Remaining heuristic matches were false positives (for example CSS selectors containing `ask-`) or non-secret test/runtime sentinels. No matched values were printed or included in this report.
- Final working-tree candidate scan covered 984 publishable files: **0 high-confidence secret matches**, **0 non-example email matches**; the only sensitive-path matches were the two `.env` example templates. One generic assignment match is the local browser-runtime probe marker, not a credential.
- After the sanitized snapshot commit, a fresh text-file scan covered 442 text/config files: **0 key-shaped strings**, **0 private-key headers**, **0 user-profile paths**, **0 non-example emails**. Six credential-pattern assignments were reviewed by path and classified as test placeholders or the local browser probe marker; their values were not printed.
- A reachable-history object scan covered 1,906 Git objects and found five key-shaped strings in three legacy test files only; they occur in test fixtures/expected Authorization values, not runtime configuration. They no longer appear in the sanitized working tree. The final repository will use a new root commit so these old objects are not pushed.
- The Docker test stack used synthetic database credentials only, no model keys, and made no paid AI call.

## BGE-M3

The bilingual deployment/install guides link the official `BAAI/bge-m3` model card, explain external model hosting, the OpenAI-compatible `/embeddings` endpoint, 1024-dimensional vectors, and host/Docker-network connection patterns. Weights are not committed or included in default images.

## Docker qualification

Docker Engine became available for explicitly approved isolated testing. Existing Compose projects were left untouched. The final-candidate test used a unique project name, separate loopback ports, synthetic database credentials, and disabled automatic cover generation.

- Compose config validation passed with a process-local synthetic `POSTGRES_PASSWORD`; no `.env` file was created.
- The first cold build completed, but startup exposed a Windows-checkout deployment defect: without an explicit attribute, `docker/container-entrypoint.sh` was checked out with CRLF, so Linux interpreted the shebang as `/bin/sh\r` and exited with `no such file or directory`.
- Added `.gitattributes` with `eol=lf` for this entrypoint and verified the indexed blob contains LF only. Rebuilt Backend/Worker from the corrected checkout; PostgreSQL, Redis, Backend, Worker, and Frontend then all became healthy.
- Alembic reported `n0p1q2r3s4t5 (head)`. `/health`, `/ready`, `/LICENSE`, and `/` returned HTTP 200; `/LICENSE` was 35,012 bytes.
- Playwright headless smoke at 1440×900: HTTP 200, page title `InsightHub`, React root rendered, LICENSE route returned 200, zero failed requests.
- A synthetic marker row survived full Compose stop/start; readiness returned 200 and marker count remained 1. The test-only project and its three synthetic volumes were then removed.
- No USER database, queue, volume, credential, or cover task was accessed.

## Tests and known limits

- Scoped backend tests (`test_analysis.py`, `test_capability_probe.py`, `test_llm_provider_credentials.py`, `test_maintenance.py`): **62 passed** on a dedicated test database and repository-local temp directory.
- A broader run had 82 passed / 6 failed. The redaction fixture failure was corrected; five pre-existing `test_llm_routing.py` expectations still assume retired DeepSeek/LOCAL deployments and legacy SiliconFlow structured-output capabilities. They were not changed because this release-preparation work excludes business-code changes.
- The first test invocation used the wrong working directory; a later run exposed the sandboxed default C: temp path. The scoped rerun passed with the repository-local `--basetemp`.
- After the final license, documentation, test-fixture, Vitest configuration, and LF entrypoint edits, the frontend suite passed: **24 files / 63 tests**. `npm run lint` exited 0 with three existing warnings; `npm run build` exited 0 with the existing large-chunk warning. `scripts/verify_release.ps1` exited 0. Full application `verify.ps1` was not run because it exercises the live app/data runtime rather than the isolated release snapshot.

## GitHub target and publication safety

- GitHub metadata confirms `sabimonkey/InsightHub` is public, owner-controlled, and size 0. The branches endpoint returned `[]`; tag refs returned HTTP 409 `Git Repository is empty`; an elevated `git ls-remote --heads --tags origin` also returned no refs. No unrelated same-name repository was used.
- The release snapshot is isolated at `.tmp_release_publish_final`, and its sole remote is `https://github.com/sabimonkey/InsightHub.git`. Only the sanitized `main` and `v1.0.0` tag are publication candidates. No force push is planned; the stale private-snapshot tag is excluded.
- Git Credential Manager reported an already-cached credential without disclosing its value; GitHub operations will use that credential only for the user-authorized push and Release creation. No app-provider API key is used, copied, logged, or published.

## AGPL network/interface notice review

- GNU's official guidance describes AGPL source offers for users interacting remotely with a modified version and defines appropriate legal notices for interactive interfaces when conveying covered software. The exact application to a hosted release depends on the deployed version and distribution facts; this report does not replace legal advice. [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html), [GNU AGPL network FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#AGPLv3InteractingRemotely), [GNU license guidance](https://www.gnu.org/licenses/gpl-howto.en.html).
- `AppShell` displays the AGPL-3.0-only identifier, no-warranty notice, `/LICENSE`, and corresponding source URL. This changes presentation/legal text only. Its component test passed in the full Vitest run.

## Private snapshot changes

`LICENSE`, English/Chinese README, release notes, third-party notices, bilingual deployment guides, Docker files, seven backend test files with only fake credential substitutions, `frontend/vitest.config.ts`, the AGPL/source UI notice and test, and `.gitattributes` to preserve the Linux entrypoint line ending on Windows checkouts.

The report's target URLs are fixed. The final commit/tag are created after the report and audit are complete. The GitHub Release is a separate publication step after the verified branch and tag push; this qualification report alone does not imply that the remote Release already exists.
