import type {
  AnalysisRunView,
  AnalysisView,
  DeploymentProbeResult,
  DiscoveryView,
  InboxFilter,
  InboxPage,
  IngestResponse,
  LlmProvider,
  SourceDetail,
  WorkflowRoute,
} from './types'

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string }
    return body.message ?? `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

export async function ingestUrl(url: string): Promise<IngestResponse> {
  const response = await fetch('/api/ingest/url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<IngestResponse>
}

export async function ingestText(text: string): Promise<IngestResponse> {
  const response = await fetch('/api/ingest/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<IngestResponse>
}

export async function ingestFile(file: File): Promise<IngestResponse> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/ingest/file', { method: 'POST', body: form })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<IngestResponse>
}

export async function ingestFiles(files: File[]): Promise<IngestResponse[]> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file)
  }
  const response = await fetch('/api/ingest/files', { method: 'POST', body: form })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as {
    results: Array<{
      ok: boolean
      message: string | null
      filename: string | null
      duplicate_detected: boolean
      duplicate_reason: string | null
      source_id: string | null
      ingestion_id: string | null
    }>
  }
  return body.results.map((result) => {
    if (!result.ok || !result.source_id || !result.ingestion_id) {
      throw new Error(result.message ?? `${result.filename ?? '文件'} 上传失败`)
    }
    return {
      source: {
        id: result.source_id,
        source_type: 'FILE',
        display_name: result.filename,
        original_url: null,
        canonical_url: null,
        content_hash: null,
        status: 'STORED',
        created_at: '',
        updated_at: '',
      },
      ingestion: {
        id: result.ingestion_id,
        source_item_id: result.source_id,
        ingestion_type: 'FILE',
        original_input: result.filename ?? '',
        collected_at: '',
        duplicate_detected: result.duplicate_detected,
        duplicate_reason: result.duplicate_reason,
        status: 'STORED',
        created_at: '',
      },
      asset: null,
      duplicate_detected: result.duplicate_detected,
      duplicate_reason: result.duplicate_reason,
      message: result.message ?? '',
    }
  })
}

export async function fetchResearchNote(sourceId: string): Promise<import('./types').ResearchNote> {
  const response = await fetch(`/api/sources/${sourceId}/note`)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<import('./types').ResearchNote>
}

export async function fetchInbox(filter: InboxFilter, page = 1, pageSize = 20): Promise<InboxPage> {
  const params = new URLSearchParams({
    filter,
    page: String(page),
    page_size: String(pageSize),
  })
  const response = await fetch(`/api/inbox?${params.toString()}`)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<InboxPage>
}

export async function reextractSource(sourceId: string): Promise<void> {
  const response = await fetch(`/api/sources/${sourceId}/reextract`, { method: 'POST' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function fetchSource(sourceId: string): Promise<SourceDetail> {
  const response = await fetch(`/api/sources/${sourceId}`)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<SourceDetail>
}

export async function fetchDiscovery(sourceId: string): Promise<DiscoveryView> {
  const response = await fetch(`/api/sources/${sourceId}/discovery`)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<DiscoveryView>
}

export async function startDiscovery(sourceId: string): Promise<void> {
  const response = await fetch(`/api/sources/${sourceId}/discover`, { method: 'POST' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function confirmCandidate(candidateId: string): Promise<void> {
  const response = await fetch(`/api/source-candidates/${candidateId}/confirm`, { method: 'POST' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function rejectCandidate(candidateId: string): Promise<void> {
  const response = await fetch(`/api/source-candidates/${candidateId}/reject`, { method: 'POST' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function fetchAnalysis(sourceId: string, runId?: string): Promise<AnalysisView> {
  const params = runId ? `?run_id=${runId}` : ''
  const response = await fetch(`/api/sources/${sourceId}/analysis${params}`)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<AnalysisView>
}

const TERMINAL_ANALYSIS = new Set(['SUCCEEDED', 'PARTIAL', 'FAILED'])

export async function startAnalysisRun(
  sourceId: string,
  reanalyze: boolean,
  providerType?: string,
): Promise<AnalysisRunView> {
  const path = reanalyze ? 'reanalyze' : 'analyze'
  const response = await fetch(`/api/sources/${sourceId}/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_type: providerType ?? null }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<AnalysisRunView>
}

export async function analyzeSource(sourceId: string, providerType?: string): Promise<void> {
  await startAnalysisRun(sourceId, false, providerType)
}

export async function reanalyzeSource(sourceId: string, providerType?: string): Promise<void> {
  await startAnalysisRun(sourceId, true, providerType)
}

export async function waitForAnalysis(
  sourceId: string,
  runId?: string,
  timeoutMs = 120_000,
  onTick?: (view: AnalysisView) => void,
): Promise<AnalysisView> {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const view = await fetchAnalysis(sourceId, runId)
    onTick?.(view)
    const status = view.run?.status
    if (status && TERMINAL_ANALYSIS.has(status)) {
      return view
    }
    await new Promise((resolve) => setTimeout(resolve, 800))
  }
  throw new Error('分析超时，请稍后在资料摘要中查看状态。')
}

export async function analyzeSourceAndWait(sourceId: string, reanalyze = false, providerType?: string): Promise<AnalysisView> {
  const run = await startAnalysisRun(sourceId, reanalyze, providerType)
  return waitForAnalysis(sourceId, run.id)
}

export async function fetchProviders(): Promise<LlmProvider[]> {
  const response = await fetch('/api/llm/providers')
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<LlmProvider[]>
}

export async function testProvider(providerId: string): Promise<DeploymentProbeResult> {
  const response = await fetch(`/api/llm/providers/${providerId}/test`, { method: 'POST' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<DeploymentProbeResult>
}

export async function testDeployment(deploymentId: string): Promise<DeploymentProbeResult> {
  const response = await fetch(`/api/llm/deployments/${deploymentId}/test`, { method: 'POST' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<DeploymentProbeResult>
}

export async function createDeployment(
  providerId: string,
  body: { display_name: string; model_id: string; enabled?: boolean; capabilities?: Record<string, unknown> },
): Promise<{ id: string }> {
  const response = await fetch(`/api/llm/providers/${providerId}/deployments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<{ id: string }>
}

export async function updateDeployment(
  deploymentId: string,
  body: { display_name?: string; model_id?: string; enabled?: boolean; capabilities?: Record<string, unknown> },
): Promise<void> {
  const response = await fetch(`/api/llm/deployments/${deploymentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function fetchDeleteDeploymentPreview(deploymentId: string): Promise<{
  ok: boolean
  code?: string
  provider_name?: string
  model_id?: string
  routes?: string[]
  can_delete?: boolean
  history_preserved?: boolean
}> {
  const response = await fetch(`/api/llm/deployments/${deploymentId}/delete-preview`)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json()
}

export async function deleteDeployment(deploymentId: string): Promise<void> {
  const response = await fetch(`/api/llm/deployments/${deploymentId}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function fetchCoverPrompt(sourceId: string, colorScheme = 'auto'): Promise<{
  ok: boolean
  title?: string
  prompt?: string
  prompt_char_count?: number
  max_prompt_chars?: number
  default_target_chars?: number
  content_usable?: boolean
  model?: string
  provider?: string
  color_scheme?: string
  budget_used?: number
  monthly_budget?: number
  budget_available?: boolean
  current_cover_url?: string | null
  budget_kind?: string
  message?: string
  code?: string
  prompt_revision?: number
  prompt_version?: string
  prompt_preview_token?: string
}> {
  const response = await fetch(`/api/sources/${sourceId}/cover/prompt?color_scheme=${encodeURIComponent(colorScheme)}`)
  return response.json()
}

export type GlobalCoverPromptConfig = {
  ok: boolean
  prompt: string
  revision: number
  version: string
  updated_at?: string | null
  max_global_prompt_chars: number
  system_default_prompt: string
  message?: string
  code?: string
}

export async function fetchGlobalCoverPrompt(): Promise<GlobalCoverPromptConfig> {
  const response = await fetch('/api/cover/prompt-config')
  return response.json()
}

export async function saveGlobalCoverPrompt(prompt: string): Promise<GlobalCoverPromptConfig> {
  const response = await fetch('/api/cover/prompt-config', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }),
  })
  return response.json()
}

export async function resetGlobalCoverPrompt(): Promise<GlobalCoverPromptConfig> {
  const response = await fetch('/api/cover/prompt-config/reset', { method: 'POST' })
  return response.json()
}

export async function previewGlobalCoverPrompt(input: {
  source_id: string; global_prompt: string; color_scheme?: string; personalization?: string
}): Promise<{
  ok: boolean; title?: string; source_id?: string; prompt?: string; global_prompt?: string
  prompt_char_count?: number; max_prompt_chars?: number; prompt_revision?: number; prompt_version?: string
  color_scheme?: string; personalization?: string; content_usable?: boolean; code?: string; message?: string
  topic?: string; palette_direction?: string
}> {
  const response = await fetch('/api/cover/prompt-preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  return response.json()
}

export type CoverStatusResponse = {
  ok: boolean
  run_id?: string
  status?: string
  stage?: string
  lifecycle?: 'idle' | 'running' | 'succeeded' | 'failed'
  display_ready?: boolean
  terminal_success?: boolean
  error_code?: string
  error_message?: string
  has_generated_cover?: boolean
  cover_url?: string | null
  current_cover_url?: string | null
  cover_origin?: string | null
  candidate_asset_id?: string | null
  candidate_cover_url?: string | null
  candidate_is_current?: boolean
  candidate_review_state?: 'APPLIED' | 'KEPT_OLD' | null
  code?: string
  message?: string
}

export async function startCoverGenerate(
  sourceId: string,
  body: { prompt?: string; confirm_send: boolean; color_scheme?: string; idempotency_key: string; prompt_revision?: number; prompt_preview_token?: string },
): Promise<CoverStatusResponse> {
  const response = await fetch(`/api/sources/${sourceId}/cover/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return response.json()
}

export async function reviewCoverCandidate(
  runId: string,
  action: 'keep_old' | 'use_new',
): Promise<CoverStatusResponse> {
  const response = await fetch(`/api/cover/runs/${runId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  })
  return response.json()
}

export async function fetchCoverStatus(sourceId: string, runId?: string): Promise<CoverStatusResponse> {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
  const response = await fetch(`/api/sources/${sourceId}/cover/status${query}`)
  return response.json()
}

export async function addUserTextSupplement(sourceId: string, text: string): Promise<{
  run?: { id: string; status: string }
  document?: { id: string; status: string; metadata_json?: Record<string, unknown> }
  code?: string
  message?: string
}> {
  const response = await fetch(`/api/sources/${sourceId}/supplement`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  const body = await response.json()
  if (!response.ok) throw new Error(body.message || body.code || '保存补充原文失败')
  return body
}

export type CoverSettingsResponse = {
  ok: boolean
  auto_enabled?: boolean
  requires_analysis?: boolean
  monthly_budget?: number
  budget_kind?: string
  budget_range?: { min: number; max: number }
  code?: string
  message?: string
  detail?: string
}

export type MiniMaxTokenPlanStatus = {
  ok: boolean
  provider?: string
  mode?: string
  status?: string
  code?: string | null
  http_status?: number
  current_interval_usage_count?: number
  current_interval_remaining_percent?: number
  weekly_usage_count?: number
  weekly_remaining_percent?: number
  quota_unit?: string
  message?: string
}

export async function fetchCoverSettings(): Promise<CoverSettingsResponse> {
  const response = await fetch('/api/cover/settings')
  const body = (await response.json()) as CoverSettingsResponse
  if (!response.ok) throw new Error(body.message || body.detail || body.code || `设置请求失败（${response.status}）`)
  return body
}

export async function patchCoverSettings(autoEnabled: boolean | undefined, monthlyBudget?: number): Promise<CoverSettingsResponse> {
  const response = await fetch('/api/cover/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...(autoEnabled == null ? {} : { auto_enabled: autoEnabled }), ...(monthlyBudget == null ? {} : { monthly_budget: monthlyBudget }) }),
  })
  const body = (await response.json()) as CoverSettingsResponse
  if (!response.ok) throw new Error(body.message || body.detail || body.code || `设置请求失败（${response.status}）`)
  return body
}

export async function fetchMiniMaxTokenPlan(): Promise<MiniMaxTokenPlanStatus> {
  const response = await fetch('/api/cover/token-plan')
  return response.json()
}

export type CoverQueueSummary = {
  active: number
  queued: number
  generating: number
  succeeded: number
  failed: number
  monthly_used: number
  monthly_attempts?: number
  monthly_budget: number
  budget_kind?: string
  auto_enabled: boolean
}

export type CoverQueueJob = {
  run_id: string
  source_id: string
  source_title: string
  status: string
  stage: string
  terminal_success: boolean
  error_code?: string | null
  error_message?: string | null
  is_active: boolean
  can_retry?: boolean
  updated_at?: string
}

export async function fetchCoverQueue(): Promise<{ ok: boolean; summary?: CoverQueueSummary; jobs?: CoverQueueJob[] }> {
  const response = await fetch('/api/cover/queue')
  return response.json()
}

export async function retryCoverRun(runId: string): Promise<{ ok: boolean; code?: string; message?: string }> {
  const response = await fetch(`/api/cover/runs/${runId}/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_send: true }),
  })
  return response.json()
}

export type AnalysisQueueSummary = {
  active: number
  pending: number
  running: number
  succeeded: number
  partial: number
  failed: number
}

export type AnalysisQueueJob = {
  run_id: string
  source_id: string
  source_title: string
  status: string
  stage: string
  stage_label: string
  provider_type?: string
  model_name: string
  is_simulated?: boolean
  error_code?: string | null
  error_message?: string | null
  can_retry?: boolean
}

export async function fetchAnalysisQueue(): Promise<{ ok: boolean; summary?: AnalysisQueueSummary; jobs?: AnalysisQueueJob[] }> {
  const response = await fetch('/api/analysis/queue')
  return response.json()
}

export type AnalysisBackfillPreview = {
  ok?: boolean
  total_sources?: number
  default_candidate_count: number
  fresh_candidate_count?: number
  retry_failed_count?: number
  retry_partial_count?: number
  active_task_count?: number
  explanation?: string | null
  buckets: Record<string, { count: number; sample_source_ids: string[] }>
  cover_side_effect?: {
    auto_cover_enabled: boolean
    monthly_budget: number
    monthly_used: number
    monthly_remaining: number
    note: string
  } | null
  code?: string
  message?: string
}

export async function fetchAnalysisBackfillPreview(): Promise<AnalysisBackfillPreview> {
  const response = await fetch('/api/analysis/backfill/preview')
  return response.json()
}

export async function startAnalysisBackfill(body: {
  confirm: boolean
  source_ids?: string[]
  include_partial?: boolean
  mode?: 'fresh' | 'retry_failed' | 'retry_partial'
}): Promise<{
  ok: boolean
  enqueued_run_ids?: string[]
  skipped?: Record<string, number>
  code?: string
  message?: string
}> {
  const response = await fetch('/api/analysis/backfill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return response.json()
}

export async function fetchSystemStatus(): Promise<{ worker?: string }> {
  const response = await fetch('/api/system')
  if (!response.ok) return {}
  return response.json()
}

export async function fetchRoutes(): Promise<{ routes: WorkflowRoute[]; options: import('./types').WorkflowRouteOption[] }> {
  const response = await fetch('/api/llm/routes')
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { routes: WorkflowRoute[]; options: import('./types').WorkflowRouteOption[] }
  return body
}

export async function saveRoutes(routes: Record<string, string>): Promise<{ routes: WorkflowRoute[]; options: import('./types').WorkflowRouteOption[] }> {
  const response = await fetch('/api/llm/routes', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(routes),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { routes: WorkflowRoute[]; options: import('./types').WorkflowRouteOption[] }
  return body
}

export async function setProviderEnabled(providerId: string, enabled: boolean): Promise<void> {
  const response = await fetch(`/api/llm/providers/${providerId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function retireProvider(providerId: string): Promise<{ retired: boolean; history_preserved: boolean }> {
  const response = await fetch(`/api/llm/providers/${providerId}/retire`, { method: 'POST' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function saveProviderCredential(providerId: string, apiKey: string): Promise<{
  ok: boolean
  credential_source: string
  configured: boolean
  api_key_state: string
}> {
  const response = await fetch(`/api/llm/providers/${providerId}/credential`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json()
}

export async function clearProviderCredential(providerId: string): Promise<{
  ok: boolean
  credential_source: string
  configured: boolean
  api_key_state: string
}> {
  const response = await fetch(`/api/llm/providers/${providerId}/credential`, { method: 'DELETE' })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json()
}
export async function fetchOrganization(sourceId: string) {
  const response = await fetch(`/api/sources/${sourceId}/organization`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function organizeSource(sourceId: string) {
  const response = await fetch(`/api/sources/${sourceId}/organize`, { method: 'POST' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchLibrary(params: Record<string, string>) {
  const query = new URLSearchParams(params)
  const response = await fetch(`/api/library?${query}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchLibraryTrash() {
  const response = await fetch('/api/library/trash')
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function trashSource(sourceId: string) {
  const response = await fetch(`/api/sources/${sourceId}/trash`, { method: 'POST' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function restoreSource(sourceId: string) {
  const response = await fetch(`/api/sources/${sourceId}/restore`, { method: 'POST' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function deleteAskSession(sessionId: string) {
  const response = await fetch(`/api/ask/sessions/${sessionId}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function clearAskSessions() {
  const response = await fetch('/api/ask/sessions/clear', { method: 'POST' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchCard(id: string) {
  const response = await fetch(`/api/knowledge-cards/${id}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchInsight(id: string) {
  const response = await fetch(`/api/commercial-insights/${id}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchCandidates() {
  const response = await fetch('/api/project-candidates')
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function promoteCandidate(id: string) {
  const response = await fetch(`/api/project-candidates/${id}/promote`, { method: 'POST' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchTopics() {
  const response = await fetch('/api/topics')
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function mergeTopics(topicId: string, canonicalId: string) {
  const response = await fetch(`/api/topics/${topicId}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ canonical_id: canonicalId }),
  })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function fetchEntities() {
  const response = await fetch('/api/entities')
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

export async function updateSourceCategories(sourceId: string, body: { add?: string[]; reject?: string[]; primary?: string }) {
  const response = await fetch(`/api/sources/${sourceId}/categories`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await readError(response))
}

export async function addManualCandidate(sourceId: string, url: string): Promise<void> {
  const response = await fetch(`/api/sources/${sourceId}/discovery/candidates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
}
