# InsightHub user guide

This guide follows the current UI: Collection, Knowledge, Search, Ask, Notes, and Settings. Available models and workflow routes depend on administrator configuration.

## 1. Collect sources

On **Collection**, choose URL, Text, or File. After submission, inspect progress in Recent Collection or the knowledge library. Web pages are fetched by the InsightHub server; login walls, anti-bot controls, or unavailable sites can prevent extraction. Supply text or a file only when you are authorized to do so; a URL alone is not page content.

## 2. Knowledge and analysis

The knowledge library keeps source references, extraction results, and available analysis. Open a source to inspect provenance, extraction status, summary, and evidence. Only content actually returned and accepted by the applicable validation is an analysis result. Model availability depends on workflow routes, credentials, quota, and source state.

## 3. Search and Ask

Search saved sources. Semantic retrieval can participate when embeddings are enabled; keyword search remains available otherwise. In Ask, submit a question and review the linked source citations. Treat generated answers as retrieval-grounded assistance and check the cited source text.

## 4. Notes

The Notes workspace previews eligible sources by date and scope. Select a topic and detail level, preview the source set, then submit generation. The backend persists task state and output; queued and running jobs must reach a terminal state. Follow the UI's partial/failure details and do not treat a failed task as a saved note.

## 5. Configure providers

In **Settings → AI Models**, inspect registered providers, deployments, routes, and credential state. Add model keys through the encrypted vault. Configuring a provider does not imply that every workflow uses it; verify the actual route and model test. MiniMax covers are optional and independent. The app's local safety cap is not the provider's remaining quota.

## Privacy and backups

Cloud models receive the inputs required by their workflows. Do not send data that should not leave your environment. Back up the database and `app_data` volume together; app data includes user uploads, derived assets, and credential-vault key material. See the [deployment guide](DEPLOYMENT.en.md).
