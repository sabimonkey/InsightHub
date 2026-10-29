import { Button, Descriptions, Drawer, Input, List, Tag } from 'antd'
import { useEffect, useState } from 'react'
import type { AnalysisView, DiscoveryView, SourceDetail } from '../types'

type SourceDetailDrawerProps = {
  open: boolean
  detail: SourceDetail | null
  discovery: DiscoveryView | null
  analysis: AnalysisView | null
  organization?: {
    categories: Array<{ slug: string; name: string; origin: string; is_primary: boolean }>
    topics: Array<{ name: string }>
    entities: Array<{ name: string }>
    tags: string[]
    knowledge_card_id: string | null
    commercial_insight_id: string | null
    project_candidate_id: string | null
    collection_origin: string
  } | null
  onClose: () => void
  onReextract?: (sourceId: string) => void
  onDiscover?: (sourceId: string) => void
  onConfirm?: (candidateId: string) => void
  onReject?: (candidateId: string) => void
  onManual?: (sourceId: string, url: string) => void
  onOpenTarget?: (sourceId: string) => void
  onAnalyze?: (sourceId: string) => void
  onSelectRun?: (sourceId: string, runId: string) => void
  focusChunkId?: string | null
}

function openOriginal(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

function extractionLabel(status: string | null | undefined): string {
  if (!status) {
    return '未解析'
  }
  const labels: Record<string, string> = {
    PENDING: '等待',
    RUNNING: '处理中',
    SUCCEEDED: '成功',
    PARTIAL: '部分成功',
    FAILED: '失败',
  }
  return labels[status] ?? status
}

export function SourceDetailDrawer({
  open,
  detail,
  discovery,
  analysis,
  organization,
  onClose,
  onReextract,
  onDiscover,
  onConfirm,
  onReject,
  onManual,
  onOpenTarget,
  onAnalyze,
  onSelectRun,
  focusChunkId,
}: SourceDetailDrawerProps) {
  const source = detail?.source
  const asset = detail?.asset
  const originalUrl = source?.original_url ?? source?.canonical_url ?? null
  const [manualUrl, setManualUrl] = useState('')
  const [activeChunk, setActiveChunk] = useState<string | null>(focusChunkId ?? null)
  useEffect(() => {
    if (!focusChunkId) {
      return
    }
    setActiveChunk(focusChunkId)
    document.getElementById(`chunk-${focusChunkId}`)?.scrollIntoView?.()
  }, [focusChunkId, detail])
  const confirmed = discovery?.relations.filter((item) => item.relation_type === 'RESOLVES_TO') ?? []
  return (
    <Drawer title="资料详情" open={open} onClose={onClose} size="large">
      {source ? (
        <>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Source ID">{source.id}</Descriptions.Item>
            <Descriptions.Item label="类型">{source.source_type}</Descriptions.Item>
            <Descriptions.Item label="加入时间">{new Date(source.created_at).toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="状态">{source.status}</Descriptions.Item>
            <Descriptions.Item label="原始 URL">{source.original_url ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="Canonical URL">{source.canonical_url ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="原文件名">{asset?.original_filename ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="SHA-256">{asset?.sha256 ?? source.content_hash ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="文件大小">{asset ? `${asset.size_bytes} B` : '—'}</Descriptions.Item>
            <Descriptions.Item label="重复关系">
              {(detail?.ingestions.length ?? 0) > 1
                ? `已有 ${detail?.ingestions.length} 次收集，复用同一 Source`
                : '首次收集'}
            </Descriptions.Item>
          </Descriptions>
          {originalUrl ? (
            <Button style={{ marginTop: 16 }} onClick={() => openOriginal(originalUrl)}>
              Open Original
            </Button>
          ) : null}
          <List
            style={{ marginTop: 24 }}
            header="收集记录"
            dataSource={detail?.ingestions ?? []}
            renderItem={(item) => (
              <List.Item>
                <div>
                  <div>{new Date(item.collected_at).toLocaleString()}</div>
                  <div>{item.duplicate_detected ? <Tag color="gold">重复</Tag> : <Tag color="green">正常</Tag>}</div>
                  <div>状态：{item.status}</div>
                </div>
              </List.Item>
            )}
          />
          <section style={{ marginTop: 24 }}>
            <h3>提取内容</h3>
            <p>解析状态：{extractionLabel(detail?.extraction?.run?.status)}</p>
            {detail?.extraction?.run?.status === 'FAILED' ? (
              <p>提取失败：{detail.extraction.run.error_message ?? detail.extraction.run.error_code}</p>
            ) : null}
            {detail?.extraction?.run?.status === 'FAILED' && onReextract ? (
              <Button onClick={() => onReextract(source.id)}>Retry</Button>
            ) : null}
            {detail?.extraction?.document ? (
              <>
                <p>标题：{detail.extraction.document.title ?? '—'}</p>
                <p>
                  提取方式：{detail.extraction.document.extractor_type} {detail.extraction.document.extractor_version}
                </p>
                {detail.extraction.document.metadata_json?.acquisition_mode === 'BROWSER' ? (
                  <p>
                    获取方式：浏览器渲染
                    {detail.extraction.document.metadata_json?.fallback_reason
                      ? `（${String(detail.extraction.document.metadata_json.fallback_reason)}）`
                      : ''}
                    {detail.extraction.document.metadata_json?.final_url
                      ? ` · 最终地址：${String(detail.extraction.document.metadata_json.final_url)}`
                      : ''}
                  </p>
                ) : null}
                <p>提取时间：{new Date(detail.extraction.document.created_at).toLocaleString()}</p>
                <pre>{detail.extraction.document.plain_text.slice(0, 2000)}</pre>
                <List
                  header="Chunks"
                  dataSource={detail.extraction.chunks}
                  renderItem={(chunk) => (
                    <List.Item id={`chunk-${chunk.id}`} style={activeChunk === chunk.id ? { background: '#fff3bf' } : undefined}>
                      <div>
                        <div>{(chunk.heading_path ?? []).join(' / ') || chunk.chunk_type}</div>
                        <div>{chunk.content}</div>
                      </div>
                    </List.Item>
                  )}
                />
              </>
            ) : null}
            {onReextract ? (
              <Button style={{ marginTop: 12 }} onClick={() => onReextract(source.id)}>
                重新提取
              </Button>
            ) : null}
          </section>
          <section style={{ marginTop: 24 }}>
            <h3>Original Source Discovery</h3>
            <p>Discovery Status：{discovery?.run?.status ?? '未运行'}</p>
            {discovery?.run?.error_message ? <p>{discovery.run.error_message}</p> : null}
            {onDiscover ? (
              <Button onClick={() => onDiscover(source.id)}>Find Original Source</Button>
            ) : null}
            {confirmed.map((relation) => (
              <div key={relation.id}>
                <p>Confirmed Source</p>
                <Button onClick={() => onOpenTarget?.(relation.to_source_id)}>{relation.to_source_id}</Button>
              </div>
            ))}
            <List
              header="候选来源"
              dataSource={discovery?.candidates ?? []}
              renderItem={(candidate) => (
                <List.Item>
                  <div>
                    <div>{candidate.title ?? candidate.normalized_candidate_url}</div>
                    <div>{candidate.normalized_candidate_url}</div>
                    <div>{candidate.publisher ?? candidate.normalized_candidate_url}</div>
                    <div>
                      {candidate.candidate_type} score {candidate.score} confidence {candidate.confidence}
                    </div>
                    <div>{candidate.match_reasons.join('；')}</div>
                    {candidate.previously_rejected ? <Tag>Previously Rejected</Tag> : null}
                    {candidate.likely_original ? <Tag>Likely Original Source</Tag> : null}
                    <Button href={candidate.candidate_url} target="_blank">
                      Open
                    </Button>
                    {candidate.status === 'PROPOSED' && onConfirm ? (
                      <Button onClick={() => onConfirm(candidate.id)}>Confirm</Button>
                    ) : null}
                    {candidate.status === 'PROPOSED' && onReject ? (
                      <Button onClick={() => onReject(candidate.id)}>Reject</Button>
                    ) : null}
                  </div>
                </List.Item>
              )}
            />
            <Input
              aria-label="手动候选 URL"
              value={manualUrl}
              onChange={(event) => setManualUrl(event.target.value)}
              placeholder="https://"
            />
            <Button
              onClick={() => {
                if (onManual && manualUrl.trim()) {
                  onManual(source.id, manualUrl.trim())
                  setManualUrl('')
                }
              }}
            >
              Add Candidate Manually
            </Button>
          </section>
          <section style={{ marginTop: 24 }}>
            <h3>AI Analysis</h3>
            {!analysis?.providers_configured ? <p>No LLM provider configured</p> : null}
            <p>Analysis Status：{analysis?.run?.status ?? '未运行'}</p>
            {analysis?.partial_warning ? <p>Analysis based on partially extracted content.</p> : null}
            {analysis?.run?.error_code === 'PRIVACY_PROVIDER_NOT_ALLOWED' ? <p>敏感资料不能使用云端模型。</p> : null}
            {analysis?.run ? (
              <p>
                {analysis.run.is_simulated ? '模拟测试（未调用真实模型） · ' : ''}{analysis.run.provider_type} / {analysis.run.model_name} / {analysis.run.prompt_name} {analysis.run.prompt_version}
              </p>
            ) : null}
            {analysis?.run?.status === 'FAILED' && onAnalyze ? <Button onClick={() => onAnalyze(source.id)}>Retry</Button> : null}
            {onAnalyze ? <Button onClick={() => onAnalyze(source.id)}>Analyze</Button> : null}
            {onAnalyze ? <Button onClick={() => onAnalyze(source.id)}>Re-analyze</Button> : null}
            {analysis?.summary ? <p>Summary：{analysis.summary}</p> : null}
            {(['FACT', 'SOURCE_CLAIM', 'INFERENCE', 'HYPOTHESIS', 'UNKNOWN', 'QUESTION'] as const).map((claimType) => (
              <div key={claimType}>
                <h4>{claimType}</h4>
                {(analysis?.claims ?? [])
                  .filter((claim) => claim.claim_type === claimType)
                  .map((claim) => (
                    <p key={claim.id}>
                      {claim.text}{' '}
                      {claim.evidence.map((item) => (
                        <Button
                          key={item.id}
                          onClick={() => {
                            setActiveChunk(item.content_chunk_id)
                            document.getElementById(`chunk-${item.content_chunk_id}`)?.scrollIntoView?.()
                          }}
                        >
                          [{item.citation}]
                        </Button>
                      ))}
                    </p>
                  ))}
              </div>
            ))}
            <p>Category Candidates：{(analysis?.category_candidates ?? []).map((item) => item.name).join(', ') || '—'}</p>
            <p>Topic Candidates：{(analysis?.topic_candidates ?? []).join(', ') || '—'}</p>
            <p>Entity Mentions：{(analysis?.entities ?? []).map((item) => item.name).join(', ') || '—'}</p>
            <h3>Organization</h3>
            <p>Categories：{(organization?.categories ?? []).map((item) => `${item.name}${item.is_primary ? ' primary' : ''} ${item.origin}`).join(', ') || '—'}</p>
            <p>Topics：{(organization?.topics ?? []).map((item) => item.name).join(', ') || '—'}</p>
            <p>Entities：{(organization?.entities ?? []).map((item) => item.name).join(', ') || '—'}</p>
            <p>Tags：{(organization?.tags ?? []).join(', ') || '—'}</p>
            {organization?.collection_origin === 'SYSTEM_DISCOVERY' ? <p>Discovered Source</p> : null}
            {organization?.knowledge_card_id ? <p>KnowledgeCard</p> : null}
            {organization?.commercial_insight_id ? <p>CommercialInsight</p> : null}
            {organization?.project_candidate_id ? <p>ProjectCandidate</p> : null}
            <h4>Analysis History</h4>
            {(analysis?.history ?? []).map((item) => (
              <Button key={item.id} onClick={() => onSelectRun?.(source.id, item.id)}>
                {item.created_at} {item.provider_type} {item.model_name} {item.prompt_version} {item.status}
              </Button>
            ))}
          </section>
        </>
      ) : null}
    </Drawer>
  )
}
