import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { formatIsoDate, resolvePreset, type DatePreset } from '../dates'

export type PreviewSource = {
  source_id: string
  title: string
  role: string
  included: boolean
  exclusion_reason: string | null
  privacy_level: string
}

export type BriefRow = {
  id: string
  title: string | null
  status: string
  job_id?: string | null
  provider_type?: string | null
  model_name?: string | null
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  latency_ms?: number | null
  completed_at?: string | null
  start_date: string
  end_date: string
  date_basis?: string
  detail_level?: string
  content_markdown: string | null
  included_source_count: number
  selected_source_count: number
  excluded_source_count: number
  exclusion_reasons: Record<string, number>
  error_code: string | null
  error_message: string | null
  regenerated_from_id?: string | null
  created_at?: string | null
  filters: { category_slugs?: string[]; topic_ids?: string[] }
  citations: Array<{ citation_number: number; content_chunk_id: string; source_item_id: string; quote_text: string | null }>
  source_index: Array<{ citation_number: number; title: string; original_url: string | null; canonical_url: string | null; filename: string | null }>
  learning_note?: {
    title: string
    highlights: string[]
    theme_notes: Array<{ title: string; summary: string; points: Array<{ text: string; label: string }> }>
    sections: Record<string, Array<{ text: string; label: string }>>
    follow_ups: string[]
  } | null
  generation_diagnostics?: {
    request_count?: number
    input_tokens?: number
    output_tokens?: number
    total_tokens?: number
    latency_ms?: number
    attempts?: Array<{ model?: string; provider?: string; http_status?: number; finish_reason?: string | null; input_tokens?: number | null; output_tokens?: number | null; latency_ms?: number | null }>
  } | null
}

export type DraftConfig = {
  start_date: string
  end_date: string
  date_basis: string
  detail_level: string
  category_slugs: string[]
  topic_ids: string[]
  activePreset: DatePreset | null
}

export type ReadingSurface =
  | { mode: 'idle' }
  | { mode: 'history'; briefId: string; brief: BriefRow | null; loading: boolean }
  | { mode: 'generation'; configSnapshot: DraftConfig; brief: BriefRow | null; polling: boolean; statusCheckFailed?: boolean }

function todayIso() {
  return formatIsoDate(new Date())
}

function monthStartIso() {
  const now = new Date()
  return formatIsoDate(new Date(now.getFullYear(), now.getMonth(), 1))
}

function defaultDraft(): DraftConfig {
  return {
    start_date: monthStartIso(),
    end_date: todayIso(),
    date_basis: 'COLLECTED_AT',
    detail_level: 'STANDARD',
    category_slugs: [],
    topic_ids: [],
    activePreset: null,
  }
}

function draftPayload(draft: DraftConfig) {
  return {
    start_date: draft.start_date,
    end_date: draft.end_date,
    date_basis: draft.date_basis,
    detail_level: draft.detail_level,
    category_slugs: draft.category_slugs,
    topic_ids: draft.topic_ids,
  }
}

async function fetchBriefRow(id: string): Promise<BriefRow | null> {
  const response = await fetch(`/api/briefs/${id}`)
  if (!response.ok) throw new Error(`读取笔记任务失败（${response.status}）`)
  const body = (await response.json()) as BriefRow | { brief: null }
  return 'brief' in body && body.brief === null ? null : (body as BriefRow)
}

function briefConfigSnapshot(brief: BriefRow): DraftConfig {
  return {
    start_date: brief.start_date,
    end_date: brief.end_date,
    date_basis: brief.date_basis ?? 'COLLECTED_AT',
    detail_level: brief.detail_level ?? 'STANDARD',
    category_slugs: brief.filters?.category_slugs ?? [],
    topic_ids: brief.filters?.topic_ids ?? [],
    activePreset: null,
  }
}

function isActiveBrief(brief: BriefRow) {
  return brief.status === 'PENDING' || brief.status === 'RUNNING'
}

export function useBriefWorkspace() {
  const [draft, setDraft] = useState<DraftConfig>(() => defaultDraft())
  const [briefs, setBriefs] = useState<BriefRow[]>([])
  const [reading, setReading] = useState<ReadingSurface>({ mode: 'idle' })
  const [preview, setPreview] = useState<PreviewSource[]>([])
  const [previewStats, setPreviewStats] = useState<{
    total_in_range: number
    included_for_brief: number
    extraction_ready_count?: number
    analysis_ready_count?: number
    claims_ready_count?: number
    exclusion_reasons: Record<string, number>
  } | null>(null)
  const [previewDiagnosis, setPreviewDiagnosis] = useState<{ code: string; message: string } | null>(null)
  const [providerReady, setProviderReady] = useState(true)
  const historyLoadSeq = useRef(0)
  const generationPollSeq = useRef(0)
  const generationSubmitRef = useRef(false)
  const readingRef = useRef<HTMLElement | null>(null)

  const refreshBriefs = useCallback(async () => {
    const response = await fetch('/api/briefs')
    if (response.ok) {
      const body = (await response.json()) as { briefs: BriefRow[] }
      setBriefs(body.briefs)
      return body.briefs
    }
    return [] as BriefRow[]
  }, [])

  const pollBrief = useCallback(async (briefId: string, pollSeq: number, initial: BriefRow) => {
    let brief = initial
    let intervalMs = 750
    const deadline = Date.now() + 16 * 60_000
    while (isActiveBrief(brief) && Date.now() < deadline) {
      if (generationPollSeq.current !== pollSeq) return brief
      await new Promise((resolve) => setTimeout(resolve, intervalMs))
      try {
        const next = await fetchBriefRow(briefId)
        if (next) {
          brief = next
          setReading((surface) =>
            surface.mode === 'generation' && surface.brief?.id === briefId
              ? { ...surface, brief, polling: isActiveBrief(brief), statusCheckFailed: false }
              : surface,
          )
        } else {
          brief = {
            ...brief,
            status: 'FAILED',
            error_code: 'BRIEF_NOT_FOUND',
            error_message: '后台任务记录当前不可读取，请刷新历史并确认任务状态。',
          }
        }
      } catch {
        setReading((surface) =>
          surface.mode === 'generation' && surface.brief?.id === briefId ? { ...surface, statusCheckFailed: true } : surface,
        )
      }
      if (!isActiveBrief(brief)) break
      intervalMs = Math.min(5000, Math.round(intervalMs * 1.5))
    }
    return brief
  }, [])

  useEffect(() => {
    let disposed = false
    void refreshBriefs().then((rows) => {
      if (disposed) return
      const active = rows.find(isActiveBrief)
      if (!active) {
        const latest = rows
          .filter((item) => item.status !== 'PENDING' && item.status !== 'RUNNING')
          .reduce<BriefRow | null>((current, item) => {
            if (!current) return item
            const itemTime = Date.parse(item.completed_at ?? item.created_at ?? '') || 0
            const currentTime = Date.parse(current.completed_at ?? current.created_at ?? '') || 0
            return itemTime > currentTime ? item : current
          }, null)
        if (latest) setReading({ mode: 'history', briefId: latest.id, brief: latest, loading: false })
        return
      }
      const configSnapshot = briefConfigSnapshot(active)
      const pollSeq = generationPollSeq.current + 1
      generationPollSeq.current = pollSeq
      setReading({ mode: 'generation', configSnapshot, brief: active, polling: true })
      void pollBrief(active.id, pollSeq, active).then((brief) => {
        if (disposed || generationPollSeq.current !== pollSeq) return
        setReading({ mode: 'generation', configSnapshot, brief, polling: false })
        void refreshBriefs()
      })
    })
    void fetch('/api/llm/providers')
      .then(async (response) => {
        if (!response.ok) {
          setProviderReady(false)
          return
        }
        const rows = (await response.json()) as Array<{ configured?: boolean }>
        setProviderReady(rows.some((item) => item.configured))
      })
      .catch(() => setProviderReady(false))
    return () => {
      disposed = true
      generationPollSeq.current += 1
    }
  }, [pollBrief, refreshBriefs])

  const patchDraft = useCallback((patch: Partial<DraftConfig>) => {
    setDraft((current) => ({ ...current, ...patch }))
  }, [])

  const applyPreset = useCallback((preset: DatePreset) => {
    if (preset === 'custom') return
    const range = resolvePreset(preset)
    setDraft((current) => ({
      ...current,
      start_date: range.start,
      end_date: range.end,
      activePreset: preset,
    }))
  }, [])

  const selectHistory = useCallback(async (item: BriefRow) => {
    generationPollSeq.current += 1
    const seq = historyLoadSeq.current + 1
    historyLoadSeq.current = seq
    setReading({ mode: 'history', briefId: item.id, brief: item, loading: true })
    const full = await fetchBriefRow(item.id)
    if (historyLoadSeq.current !== seq) return
    setReading({ mode: 'history', briefId: item.id, brief: full ?? item, loading: false })
  }, [])

  const runPreview = useCallback(async () => {
    const response = await fetch('/api/briefs/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(draftPayload(draft)),
    })
    if (response.ok) {
      const body = (await response.json()) as {
        sources: PreviewSource[]
        stats?: { total_in_range: number; included_for_brief: number; exclusion_reasons: Record<string, number> }
        diagnosis?: { code: string; message: string }
      }
      setPreview(body.sources)
      setPreviewStats(body.stats ?? null)
      setPreviewDiagnosis(body.diagnosis ?? null)
    }
  }, [draft])

  const submitNew = useCallback(async () => {
    const configSnapshot: DraftConfig = { ...draft, category_slugs: [...draft.category_slugs], topic_ids: [...draft.topic_ids] }
    const pollSeq = generationPollSeq.current + 1
    generationPollSeq.current = pollSeq
    setReading({ mode: 'generation', configSnapshot, brief: null, polling: true })
    await runPreview()
    const response = await fetch('/api/briefs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(draftPayload(configSnapshot)),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: { message?: string }; message?: string }
      setReading({
        mode: 'generation',
        configSnapshot,
        brief: {
          id: 'failed-create',
          title: null,
          status: 'FAILED',
          start_date: configSnapshot.start_date,
          end_date: configSnapshot.end_date,
          content_markdown: null,
          included_source_count: 0,
          selected_source_count: 0,
          excluded_source_count: 0,
          exclusion_reasons: {},
          error_code: 'CREATE_FAILED',
          error_message: body.detail?.message || body.message || '无法启动学习笔记生成',
          filters: { category_slugs: configSnapshot.category_slugs },
          citations: [],
          source_index: [],
          learning_note: null,
        },
        polling: false,
      })
      return { ok: false as const, message: body.detail?.message || body.message }
    }
    let brief = (await response.json()) as BriefRow
    setReading({ mode: 'generation', configSnapshot, brief, polling: true })
    brief = await pollBrief(brief.id, pollSeq, brief)
    if (generationPollSeq.current !== pollSeq) return { ok: true as const, brief }
    setReading({ mode: 'generation', configSnapshot, brief, polling: false })
    await refreshBriefs()
    requestAnimationFrame(() => {
      readingRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
    })
    return { ok: true as const, brief }
  }, [draft, pollBrief, refreshBriefs, runPreview])

  const generateNew = useCallback(async () => {
    if (generationSubmitRef.current) {
      return { ok: false as const, message: '笔记任务正在提交，请勿重复点击。' }
    }
    generationSubmitRef.current = true
    try {
      return await submitNew()
    } finally {
      generationSubmitRef.current = false
    }
  }, [submitNew])

  const regenerateReading = useCallback(async () => {
    const target =
      reading.mode === 'history' && reading.brief
        ? reading.brief
        : reading.mode === 'generation' && reading.brief
          ? reading.brief
          : null
    if (!target) return
    const pollSeq = generationPollSeq.current + 1
    generationPollSeq.current = pollSeq
    const configSnapshot = briefConfigSnapshot(target)
    setReading({ mode: 'generation', configSnapshot, brief: target, polling: true })
    const response = await fetch(`/api/briefs/${target.id}/regenerate`, { method: 'POST' })
    if (!response.ok) {
      setReading({ mode: 'history', briefId: target.id, brief: target, loading: false })
      return
    }
    let brief = (await response.json()) as BriefRow
    setReading({ mode: 'generation', configSnapshot, brief, polling: true })
    brief = await pollBrief(brief.id, pollSeq, brief)
    setReading({ mode: 'generation', configSnapshot, brief, polling: false })
    await refreshBriefs()
  }, [pollBrief, reading, refreshBriefs])

  const resumePolling = useCallback(async () => {
    if (reading.mode !== 'generation' || !reading.brief || !isActiveBrief(reading.brief)) return
    const current = reading.brief
    const configSnapshot = reading.configSnapshot
    const pollSeq = generationPollSeq.current + 1
    generationPollSeq.current = pollSeq
    setReading({ ...reading, polling: true, statusCheckFailed: false })
    const brief = await pollBrief(current.id, pollSeq, current)
    if (generationPollSeq.current !== pollSeq) return
    setReading({ mode: 'generation', configSnapshot, brief, polling: false })
    await refreshBriefs()
  }, [pollBrief, reading, refreshBriefs])

  const deleteBrief = useCallback(async (briefId: string) => {
    const response = await fetch(`/api/briefs/${briefId}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string | { message?: string }; message?: string }
      const detail = typeof body.detail === 'string' ? body.detail : body.detail?.message
      throw new Error(detail ? `删除失败（HTTP ${response.status}）：${detail}` : body.message || `删除失败（HTTP ${response.status}）`)
    }
    if ((reading.mode === 'history' && reading.briefId === briefId) || (reading.mode === 'generation' && reading.brief?.id === briefId)) {
      generationPollSeq.current += 1
      setReading({ mode: 'idle' })
    }
    await refreshBriefs()
  }, [reading, refreshBriefs])

  const clearBriefHistory = useCallback(async () => {
    const response = await fetch('/api/briefs', { method: 'DELETE' })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string | { message?: string }; message?: string }
      const detail = typeof body.detail === 'string' ? body.detail : body.detail?.message
      throw new Error(detail ? `清空失败（HTTP ${response.status}）：${detail}` : body.message || `清空失败（HTTP ${response.status}）`)
    }
    generationPollSeq.current += 1
    setReading({ mode: 'idle' })
    await refreshBriefs()
  }, [refreshBriefs])

  const sidebarActiveId = useMemo(() => {
    if (reading.mode === 'history') return reading.briefId
    if (reading.mode === 'generation' && reading.brief?.id) return reading.brief.id
    return null
  }, [reading])

  const draftDiffersFromHistory = useMemo(() => {
    if (reading.mode !== 'history' || !reading.brief) return false
    const b = reading.brief
    return b.start_date !== draft.start_date || b.end_date !== draft.end_date
  }, [draft.end_date, draft.start_date, reading])

  return {
    draft,
    patchDraft,
    applyPreset,
    briefs,
    refreshBriefs,
    reading,
    readingRef,
    selectHistory,
    runPreview,
    generateNew,
    regenerateReading,
    resumePolling,
    deleteBrief,
    clearBriefHistory,
    preview,
    previewStats,
    previewDiagnosis,
    providerReady,
    sidebarActiveId,
    draftDiffersFromHistory,
  }
}
