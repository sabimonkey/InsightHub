export type SourceSummary = {
  id: string
  source_type: string
  display_name: string | null
  original_url: string | null
  canonical_url: string | null
  content_hash: string | null
  status: string
  created_at: string
  updated_at: string
}

export type IngestionSummary = {
  id: string
  source_item_id: string | null
  ingestion_type: string
  original_input: string
  collected_at: string
  duplicate_detected: boolean
  duplicate_reason: string | null
  status: string
  created_at: string
}

export type AssetSummary = {
  id: string
  original_filename: string
  stored_path: string
  mime_type: string
  size_bytes: number
  sha256: string
}

export type IngestResponse = {
  source: SourceSummary
  ingestion: IngestionSummary
  asset: AssetSummary | null
  duplicate_detected: boolean
  duplicate_reason: string | null
  message: string
}

export type FileIngestResult = {
  filename: string | null
  ok: boolean
  code: string | null
  message: string | null
  duplicate_detected: boolean
  duplicate_reason: string | null
  source_id: string | null
  ingestion_id: string | null
}

export type ResearchNoteReading = {
  core_summary: { paragraphs: string[] } | null
  core_content?: {
    title?: string | null
    items: Array<{ text: string; url?: string | null }>
  } | null
  core_points: string[]
  important_reminders?: string[] | null
  inferences_and_open?: {
    inferences: string[]
    open_questions: string[]
  } | null
  source_and_evidence: {
    source_type_label: string
    author: string | null
    collected_at: string | null
    original_url: string | null
    evidence_summary: {
      verified_count: number
      items: Array<{
        conclusion: string
        quotes: Array<{ text: string; source_label: string }>
      }>
    }
  }
}

export type ResearchNote = {
  source_id: string
  title: string
  source_type: string
  source_type_label?: string | null
  author?: string | null
  original_url: string | null
  canonical_url: string | null
  collected_at: string | null
  analysis_status: string
  analysis_status_code: string | null
  analysis_latest_status_code?: string | null
  export_enabled?: boolean
  analysis_progress?: {
    run_id: string
    status: string
    stage: string
    stage_label: string
    provider?: string | null
    model_name?: string | null
  } | null
  analysis_failure?: {
    error_code: string | null
    error_message: string | null
    user_message: string
    run_id: string
    supersedes_content: boolean
  } | null
  partial_summary?: string | null
  partial_issues?: string[]
  reading?: ResearchNoteReading | null
  summary: string | null
  highlights: Array<{ text: string; claim_type: string; label: string }>
  claim_groups: Record<string, Array<{ id: string; text: string; evidence: Array<{ id: string; quote_text: string | null }> }>>
  categories: Array<{ slug: string; name: string }>
  topics: Array<{ id: string; name: string }>
  analysis?: {
    run_id?: string | null
    status?: string | null
    provider?: string | null
    provider_type?: string | null
    model_name?: string | null
    is_simulated?: boolean
    untrusted_for_user_research?: boolean
    current_run_is_simulated?: boolean
    prompt_name?: string | null
    prompt_version?: string | null
    is_cloud?: boolean | null
    completed_at?: string | null
    latency_ms?: number | null
    total_tokens?: number | null
  }
}

export type InboxItem = {
  ingestion_id: string
  source_id: string | null
  display_name: string | null
  source_type: string | null
  collected_at: string
  status: string
  duplicate_detected: boolean
  duplicate_reason: string | null
  size_bytes: number | null
  original_url: string | null
  canonical_url: string | null
  original_filename: string | null
  extraction_status: string | null
  extraction_status_label?: string | null
  extraction_status_code?: string | null
  extraction_user_message?: string | null
  has_usable_content?: boolean
  title?: string | null
  analysis_status?: string | null
  analysis_status_code?: string | null
  summary_snippet?: string | null
}

export type DiscoveryCandidate = {
  id: string
  candidate_url: string
  normalized_candidate_url: string
  title: string | null
  author: string | null
  publisher: string | null
  candidate_type: string
  score: number
  confidence: number
  match_reasons: string[]
  rank: number
  status: string
  previously_rejected: boolean
  likely_original: boolean
}

export type DiscoveryRelation = {
  id: string
  from_source_id: string
  to_source_id: string
  relation_type: string
  confirmed_by: string
  candidate_id: string | null
  created_at: string
}

export type DiscoveryView = {
  run: {
    id: string
    status: string
    resolver_type: string
    query_summary: string | null
    error_code: string | null
    error_message: string | null
  } | null
  candidates: DiscoveryCandidate[]
  relations: DiscoveryRelation[]
}

export type InboxPage = {
  items: InboxItem[]
  page: number
  page_size: number
  total: number
}

export type ExtractionView = {
  run: {
    id: string
    status: string
    trigger: string
    extractor_type: string | null
    extractor_version: string | null
    is_current: boolean
    error_code: string | null
    error_message: string | null
    created_at: string
    updated_at: string
  } | null
  document: {
    id: string
    title: string | null
    extractor_type: string
    extractor_version: string
    status: string
    plain_text: string
    content_hash: string
    metadata_json: Record<string, unknown>
    error_code: string | null
    error_message: string | null
    created_at: string
  } | null
  chunks: Array<{
    id: string
    sequence: number
    heading_path: string[] | null
    chunk_type: string
    content: string
    char_count: number
    token_count: number | null
  }>
}

export type SourceDetail = {
  source: SourceSummary
  asset: AssetSummary | null
  ingestions: IngestionSummary[]
  extraction: ExtractionView | null
}

export type InboxFilter = 'all' | 'success' | 'failed' | 'duplicate'

export type AnalysisClaim = {
  id: string
  claim_type: string
  text: string
  confidence: number | null
  importance: number | null
  evidence: Array<{
    id: string
    content_chunk_id: string
    quote_text: string | null
    page_number: number | null
    citation: number
  }>
}

export type AnalysisRunView = {
  id: string
  status: string
  provider_type: string
  model_name: string
  is_simulated?: boolean
  prompt_name: string
  prompt_version: string
  is_current: boolean
  analysis_strategy: string | null
  input_extraction_status: string | null
  input_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  error_code: string | null
  error_message: string | null
  created_at: string
  analysis_stage?: string | null
  analysis_stage_label?: string | null
}

export type AnalysisView = {
  run: AnalysisRunView | null
  summary: string | null
  partial_warning: boolean
  claims: AnalysisClaim[]
  category_candidates: Array<{ name: string; confidence?: number; reason?: string }>
  topic_candidates: string[]
  entities: Array<{ name: string; entity_type: string }>
  history: AnalysisRunView[]
  providers_configured: boolean
}

export type LlmDeployment = {
  id: string
  display_name: string
  model_id: string
  enabled: boolean
  route_ready: boolean
  capabilities?: Record<string, unknown>
}

export type LlmProvider = {
  id: string
  name: string
  provider_type: string
  base_url: string
  model: string
  is_local: boolean
  configured: boolean
  credential_configured?: boolean
  enabled: boolean
  status?: 'READY' | 'CONFIGURATION_REQUIRED' | 'DISABLED'
  is_default: boolean
  api_key_state: string
  credential_source?: string
  credential_manageable?: boolean
  capabilities?: Record<string, unknown>
  deployments: LlmDeployment[]
}

export type ProbeEntry = {
  status: string
  latency_ms?: number | null
  error_category?: string | null
  safe_message?: string | null
}

export type DeploymentProbeResult = {
  ok: boolean
  error?: string
  overall_status?: string
  provider_type?: string
  mode?: string
  message?: string
  model?: string
  resolved_model?: string
  code?: string
  latency_ms?: number
  total_latency_ms?: number
  structured_strategy?: string | null
  probes?: {
    chat?: ProbeEntry
    utf8?: ProbeEntry
    json_object?: ProbeEntry
    json_schema?: ProbeEntry
    streaming?: ProbeEntry
  }
}

export type WorkflowRouteOption = {
  deployment_id: string
  provider_type: string
  provider_name: string
  deployment_display_name: string
  model: string
  label: string
  is_local: boolean
  configured: boolean
  credential_configured?: boolean
  enabled: boolean
  status?: 'READY' | 'CONFIGURATION_REQUIRED' | 'DISABLED'
  capabilities?: Record<string, unknown>
  eligible_workflows?: Record<string, boolean>
}

export type WorkflowRoute = {
  workflow: string
  deployment_id: string
  provider_type: string
  provider_name: string
  deployment_display_name: string
  model: string
  label: string
  is_local: boolean
  configured: boolean
  enabled: boolean
}
