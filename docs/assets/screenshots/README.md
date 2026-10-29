# Screenshot provenance

These PNGs were captured from the public v1.0.0 source snapshot running in the isolated Compose project `insighthub_docs_validation_20261029` on 2026-10-29. Backend and RQ Worker were scoped to `AUTOMATION_TEST`; Chat, embeddings, and image generation used Fake providers. One fictional text source was entered through the UI for the collection and library views. It contains no USER data and is clearly labelled synthetic. No real provider key or paid model call was used.

Capture is reproducible with `scripts/capture_docs_screenshots.py` by copying it into the isolated Backend container and running it there; screenshots are first written only to that test project's `app_data` volume, then copied to this directory. Images are current UI screenshots, not product mockups. The settings overview reports its own worker state; compare it with the Compose container health check and `/ready` rather than treating screenshot text as a deployment health test.

Files: `collection-synthetic.png`, `library-synthetic.png`, `search-synthetic.png`, `ask-synthetic.png`, `notes-synthetic.png`, `settings-synthetic.png`, and `settings-models-synthetic.png`.
