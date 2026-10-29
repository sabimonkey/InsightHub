Output language: {{output_language}}
Extraction completeness: {{extraction_status}}

You are merging chunk-level structured analyses into one final JSON object for the same source.

Rules:
- Return one JSON object only. No markdown, no commentary, no thinking trace.
- Use the intermediate analyses below as the primary factual input. Do not invent facts absent from them.
- Deduplicate overlapping facts and claims. Prefer the clearest, most specific wording.
- Keep the summary concise (about 100–300 Chinese characters for Chinese sources). Lead with the core conclusion.
- Respect list limits: facts 8, source_claims 8, inferences 5, hypotheses 3, unknowns 5, questions 5.
- Every fact and source_claim must include evidence with a valid chunk_id from the list below and a short verbatim quote copied from that chunk (under 500 characters).
- Do not repeat the full source text. Do not paste entire chunks into quotes.

Valid chunk ids (evidence must reference one of these):
{{chunk_id_list}}

Intermediate analyses (JSON array):
{{intermediate_json}}
