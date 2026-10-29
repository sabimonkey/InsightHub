import { Alert, Button, Collapse, Drawer, Space, Spin, Typography, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchResearchNote, startAnalysisRun, waitForAnalysis } from '../../api'
import type { ResearchNote } from '../../types'
import { AnalysisProgress } from './AnalysisProgress'

const { Paragraph, Text, Title } = Typography

const POLL_MS = 3000
const DRAWER_WIDTH = 'min(820px, 48vw)'

type Props = {
  sourceId: string | null
  open: boolean
  onClose: () => void
}

function formatCollected(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function headerMeta(note: ResearchNote): string {
  const parts: string[] = []
  if (note.source_type_label || note.source_type) {
    parts.push(note.source_type_label || note.source_type)
  }
  const collected = formatCollected(note.collected_at)
  if (collected) parts.push(`收藏于 ${collected}`)
  parts.push(note.analysis_status)
  return parts.join(' · ')
}

function hasReadingBody(note: ResearchNote | null): boolean {
  if (!note?.reading) return false
  const paragraphs = note.reading.core_summary?.paragraphs ?? []
  const resources = note.reading.core_content?.items?.length ?? 0
  return paragraphs.length > 0 || (note.reading.core_points?.length ?? 0) > 0 || resources > 0
}

function noteMatchesSource(note: ResearchNote | null, sourceId: string | null): note is ResearchNote {
  return Boolean(note && sourceId && note.source_id === sourceId)
}

export function ResearchNoteView({ sourceId, open, onClose }: Props) {
  const [note, setNote] = useState<ResearchNote | null>(null)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [liveStage, setLiveStage] = useState<string | null>(null)
  const [liveStageLabel, setLiveStageLabel] = useState<string | null>(null)
  const loadSeq = useRef(0)
  const activeSourceRef = useRef<string | null>(null)

  useEffect(() => {
    activeSourceRef.current = sourceId
  }, [sourceId])

  const reload = useCallback(async (silent = false) => {
    const sid = sourceId
    if (!sid) return
    const seq = ++loadSeq.current
    if (!silent) setLoading(true)
    try {
      const body = await fetchResearchNote(sid)
      if (seq !== loadSeq.current || activeSourceRef.current !== sid) {
        return
      }
      if (body.source_id !== sid) {
        return
      }
      setNote(body)
      if (body.analysis_progress?.stage) {
        setLiveStage(body.analysis_progress.stage)
        setLiveStageLabel(body.analysis_progress.stage_label)
      } else if (!silent) {
        setLiveStage(null)
        setLiveStageLabel(null)
      }
      setAnalysisError(null)
    } catch {
      if (seq === loadSeq.current && activeSourceRef.current === sid && !silent) {
        setNote(null)
      }
    } finally {
      if (seq === loadSeq.current && activeSourceRef.current === sid && !silent) {
        setLoading(false)
      }
    }
  }, [sourceId])

  useEffect(() => {
    if (!open || !sourceId) {
      loadSeq.current += 1
      setNote(null)
      setAnalysisError(null)
      setAnalyzing(false)
      setSubmitting(false)
      setLiveStage(null)
      setLiveStageLabel(null)
      setLoading(false)
      return
    }
    setNote(null)
    setLiveStage(null)
    setLiveStageLabel(null)
    void reload()
  }, [open, sourceId, reload])

  const boundNote = noteMatchesSource(note, sourceId) ? note : null
  const latestCode = boundNote?.analysis_latest_status_code ?? boundNote?.analysis_status_code
  const waiting = latestCode === 'PENDING' || latestCode === 'QUEUED' || latestCode === 'RUNNING'
  const inFlight = analyzing || waiting || submitting
  const statusCode = boundNote?.analysis_status_code

  useEffect(() => {
    if (!open || !sourceId || !waiting || !boundNote) return
    const timer = window.setInterval(() => void reload(true), POLL_MS)
    return () => window.clearInterval(timer)
  }, [open, sourceId, waiting, boundNote, reload])

  async function runAnalysis(reanalyze: boolean) {
    if (!sourceId || inFlight) return
    const sid = sourceId
    setSubmitting(true)
    setAnalysisError(null)
    try {
      const run = await startAnalysisRun(sid, reanalyze)
      if (activeSourceRef.current !== sid) return
      setSubmitting(false)
      setAnalyzing(true)
      setLiveStage(run.analysis_stage ?? 'QUEUED')
      setLiveStageLabel(run.analysis_stage_label ?? '已提交，等待后台任务')
      message.success('已提交，等待后台任务')
      await reload(true)
      const view = await waitForAnalysis(sid, run.id, 120_000, (tick) => {
        if (activeSourceRef.current !== sid) return
        if (tick.run?.analysis_stage) setLiveStage(tick.run.analysis_stage)
        if (tick.run?.analysis_stage_label) setLiveStageLabel(tick.run.analysis_stage_label)
        void reload(true)
      })
      if (activeSourceRef.current !== sid) return
      if (view.run?.status === 'FAILED') {
        setAnalysisError(view.run.error_message || view.run.error_code || '分析失败')
      }
      await reload(true)
      if (view.run?.status === 'SUCCEEDED' || view.run?.status === 'PARTIAL') {
        message.success('分析完成')
      }
    } catch (caught: unknown) {
      if (activeSourceRef.current !== sid) return
      const text = caught instanceof Error ? caught.message : '分析失败'
      setAnalysisError(text)
      message.error(text)
      await reload(true)
    } finally {
      if (activeSourceRef.current === sid) {
        setSubmitting(false)
        setAnalyzing(false)
      }
    }
  }

  async function copyMarkdown() {
    if (!sourceId) return
    const response = await fetch(`/api/sources/${sourceId}/note/export?format=markdown`)
    if (!response.ok) {
      message.error('复制失败')
      return
    }
    const text = await response.text()
    await navigator.clipboard.writeText(text)
    message.success('已复制 Markdown')
  }

  async function exportPdf() {
    if (!sourceId) return
    setPdfLoading(true)
    try {
      const response = await fetch(`/api/sources/${sourceId}/note/export?format=pdf`)
      if (!response.ok) {
        message.error('PDF 导出失败')
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${boundNote?.title || 'research-note'}.pdf`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('PDF 导出失败')
    } finally {
      setPdfLoading(false)
    }
  }

  const url = boundNote?.original_url || boundNote?.canonical_url
  const reading = boundNote?.reading
  const hasContent = hasReadingBody(boundNote)
  const unanalyzed = !inFlight && !hasContent && (statusCode === null || boundNote?.analysis_status === '未分析')
  const failedNoContent = !inFlight && statusCode === 'FAILED' && !hasContent
  const failedWithPrior = Boolean(boundNote?.analysis_failure?.supersedes_content && hasContent)
  const contentPartial = boundNote?.analysis?.status === 'PARTIAL'
  const partial = (statusCode === 'PARTIAL' || contentPartial) && hasContent && !inFlight
  const exportEnabled = Boolean(boundNote?.export_enabled) && !inFlight
  const progressStage = liveStage || boundNote?.analysis_progress?.stage
  const progressLabel = liveStageLabel || boundNote?.analysis_progress?.stage_label
  const providerHint =
    boundNote?.analysis_progress?.provider && boundNote.analysis_progress.model_name
      ? `${boundNote.analysis_progress.provider} · 云端`
      : null

  const failureMessage = analysisError || boundNote?.analysis_failure?.user_message || boundNote?.analysis_failure?.error_message

  return (
    <Drawer
      className="research-note-drawer"
      title={null}
      width={DRAWER_WIDTH}
      open={open}
      onClose={onClose}
      destroyOnHidden
      styles={{ body: { paddingTop: 12, paddingBottom: 24 } }}
    >
      {loading && !boundNote ? <Spin /> : null}
      {boundNote ? (
        <div className="research-note-reading" style={{ margin: '0 auto' }}>
          <div className="drawer-title">{boundNote.title}</div>
          <Text type="secondary" className="meta-text">{headerMeta(boundNote)}</Text>

          <Space wrap className="research-note-actions">
            {unanalyzed || failedNoContent ? (
              <Button
                type="primary"
                loading={submitting || analyzing}
                disabled={inFlight}
                onClick={() => void runAnalysis(Boolean(failedNoContent))}
              >
                {submitting ? '正在提交分析任务…' : analyzing ? '分析中…' : failedNoContent ? '重新分析' : 'AI 分析'}
              </Button>
            ) : null}
            {exportEnabled ? (
              <>
                <Button onClick={() => void copyMarkdown()}>复制 Markdown</Button>
                <Button loading={pdfLoading} onClick={() => void exportPdf()}>导出 PDF</Button>
              </>
            ) : null}
            {hasContent && !unanalyzed && !failedNoContent ? (
              <Button loading={submitting || analyzing} disabled={inFlight} onClick={() => void runAnalysis(true)}>
                {submitting ? '正在提交分析任务…' : analyzing || waiting ? '分析中…' : '重新分析'}
              </Button>
            ) : null}
            {url ? (
              <Button type="link" href={url} target="_blank" rel="noreferrer">查看原文</Button>
            ) : null}
          </Space>

          {inFlight ? (
            <>
              <Alert
                type="info"
                showIcon
                title={analyzing && hasContent ? '正在重新分析' : '正在生成学习笔记'}
                description={progressLabel || (latestCode === 'PENDING' ? '任务已经提交，正在等待后台开始处理。' : '正在阅读资料并整理摘要、重点与来源依据……')}
                className="research-note-alert"
              />
              <AnalysisProgress stage={progressStage} stageLabel={progressLabel} providerHint={providerHint} />
            </>
          ) : null}

          {partial ? (
            <Alert
              type="warning"
              showIcon
              title="部分完成"
              description={(
                <div>
                  <div>
                    {boundNote.partial_summary ||
                      '已生成有效学习笔记，但有部分内容未通过来源依据校验。以下内容均来自已通过校验的结果。'}
                  </div>
                  {boundNote.partial_issues?.length ? (
                    <Collapse
                      size="small"
                      className="research-note-alert"
                      items={[
                        {
                          key: 'evidence-issues',
                          label: `查看证据校验明细（${boundNote.partial_issues.length}）`,
                          children: (
                            <ul>
                              {boundNote.partial_issues.map((issue, index) => <li key={`${index}-${issue}`}>{issue}</li>)}
                            </ul>
                          ),
                        },
                      ]}
                    />
                  ) : null}
                </div>
              )}
              className="research-note-alert"
            />
          ) : null}
          {failedWithPrior && !inFlight ? (
            <Alert type="warning" showIcon title="最新一次重新分析失败" description="当前显示上一次成功结果。" className="research-note-alert" />
          ) : null}
          {failedNoContent && !inFlight ? (
            <Alert type="error" showIcon title="AI 分析失败" description="未能生成学习笔记。" className="research-note-alert" />
          ) : null}
          {unanalyzed && !inFlight ? (
            <Alert type="info" showIcon title="尚未生成学习笔记" description="这条资料还没有 AI 学习笔记，点击 AI 分析即可生成。" className="research-note-alert" />
          ) : null}

          {failedNoContent && failureMessage && !inFlight ? (
            <Collapse
              size="small"
              className="research-note-alert"
              items={[{ key: 'fail', label: '查看详情', children: <Text type="secondary">{failureMessage}</Text> }]}
            />
          ) : null}

          {hasContent && reading ? (
            <div className="research-note-sections">
              {reading.core_summary?.paragraphs?.length ? (
                <section className="research-note-section">
                  <Title level={5} className="section-title">核心摘要</Title>
                  <div className="body-text note-core-summary">
                    {reading.core_summary.paragraphs.map((para) => (
                      <Paragraph key={para}>{para}</Paragraph>
                    ))}
                  </div>
                </section>
              ) : null}

              {reading.core_content?.items?.length ? (
                <section className="research-note-section">
                  <Title level={5} className="section-title">{reading.core_content.title || '核心内容'}</Title>
                  <ul className="body-text resource-list">
                    {reading.core_content.items.map((item) => (
                      <li key={item.text + (item.url || '')}>
                        {item.url ? (
                          <a href={item.url} target="_blank" rel="noreferrer">{item.text}</a>
                        ) : (
                          item.text
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {reading.core_points?.length ? (
                <section className="research-note-section">
                  <Title level={5} className="section-title">核心要点</Title>
                  <ul className="body-text research-note-list">
                    {reading.core_points.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {reading.important_reminders?.length ? (
                <section className="research-note-section">
                  <Title level={5} className="section-title">重要提醒</Title>
                  <ul className="body-text research-note-list">
                    {reading.important_reminders.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section className="research-note-section">
                <Title level={5} className="section-title">来源与依据</Title>
                <Paragraph className="body-text research-note-source-line">
                  <Text strong>原始资料</Text>
                  <br />
                  {reading.source_and_evidence.source_type_label}
                  {reading.source_and_evidence.author ? ` · ${reading.source_and_evidence.author}` : ''}
                </Paragraph>
                {reading.source_and_evidence.evidence_summary.verified_count > 0 ? (
                  <Collapse
                    size="small"
                    items={[
                      {
                        key: 'evidence',
                        label: `引用依据 · ${reading.source_and_evidence.evidence_summary.verified_count} 条已验证证据`,
                        children: (
                          <Space direction="vertical" style={{ width: '100%' }}>
                            {reading.source_and_evidence.evidence_summary.items.map((row) => (
                              <div key={row.conclusion} className="evidence-block">
                                <Text strong>对应结论：</Text>
                                <Paragraph className="body-text">{row.conclusion}</Paragraph>
                                {row.quotes.map((quote) => (
                                  <div key={quote.text} className="evidence-quote">
                                    <Text type="secondary">原文依据：</Text>
                                    <Paragraph className="body-text">{quote.text}</Paragraph>
                                    <Text type="secondary" className="meta-text">来源：{quote.source_label}</Text>
                                  </div>
                                ))}
                              </div>
                            ))}
                          </Space>
                        ),
                      },
                    ]}
                  />
                ) : null}
              </section>
            </div>
          ) : null}

          {!inFlight ? (
            <Collapse
              className="research-note-meta-collapse"
              items={[
                {
                  key: 'meta',
                  label: '来源与分析信息',
                  children: (
                    <div className="meta-text">
                      <p>AI 提供方：{boundNote.analysis?.provider ?? '—'}{boundNote.analysis?.is_cloud ? ' · 云端' : boundNote.analysis?.is_cloud === false ? ' · 本地' : ''}</p>
                      <p>模型：{boundNote.analysis?.is_simulated ? '模拟测试（未调用真实模型）' : ''}{boundNote.analysis?.model_name ? ` ${boundNote.analysis.model_name}` : '—'}</p>
                      <p>分析模板：{boundNote.analysis?.prompt_name ?? 'source_analysis'} {boundNote.analysis?.prompt_version ?? '—'}</p>
                      {boundNote.analysis?.completed_at ? <p>分析时间：{new Date(boundNote.analysis.completed_at).toLocaleString()}</p> : null}
                      {boundNote.analysis?.status ? <p>分析状态：{boundNote.analysis.status}</p> : null}
                      {boundNote.analysis?.untrusted_for_user_research ? <p role="alert">此资料当前只有模拟分析结果，未调用真实模型；该结果不会作为正式研究笔记或笔记综合依据。请重新运行真实模型分析。</p> : null}
                      {!boundNote.analysis?.untrusted_for_user_research && boundNote.analysis?.current_run_is_simulated ? <p role="alert">当前模拟分析结果已忽略；此处展示的是较早的真实模型分析结果。</p> : null}
                    </div>
                  ),
                },
              ]}
            />
          ) : null}
        </div>
      ) : !loading ? (
        <Paragraph>无法加载资料摘要。</Paragraph>
      ) : null}
    </Drawer>
  )
}
