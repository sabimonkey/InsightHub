import { Button, Space, Typography } from 'antd'
import { StatusBadge } from './StatusBadge'

const { Text } = Typography

type Props = {
  sourceId: string
  title: string
  sourceType?: string | null
  collectedAt?: string | null
  extractionStatusLabel?: string | null
  extractionUserMessage?: string | null
  hasUsableContent?: boolean
  summarySnippet?: string | null
  analysisStatus?: string | null
  analysisStatusCode?: string | null
  onRead: () => void
  onMore?: () => void
}

export function InboxSourceRow({
  title,
  sourceType,
  collectedAt,
  extractionStatusLabel,
  extractionUserMessage,
  hasUsableContent,
  summarySnippet,
  analysisStatus,
  analysisStatusCode,
  onRead,
  onMore,
}: Props) {
  const when = collectedAt ? new Date(collectedAt).toLocaleString() : '—'
  const extractionLine = extractionStatusLabel ?? '已保存'
  const analysisLine = analysisStatus ?? '尚未分析'
  const meta = [sourceType, when].filter(Boolean).join(' · ')
  const hasNote =
    Boolean(summarySnippet) ||
    analysisStatusCode === 'SUCCEEDED' ||
    analysisStatusCode === 'PARTIAL'
  const canRead = hasNote || Boolean(hasUsableContent)
  return (
    <div className="inbox-row" aria-label="资料卡片">
      <div className="inbox-row-main">
        <Text strong className="inbox-row-title">{title}</Text>
        <Text type="secondary" className="inbox-row-meta">{meta}</Text>
        <Text type="secondary" className="inbox-row-meta">资料：{extractionLine}</Text>
        {extractionUserMessage ? <Text type="danger">{extractionUserMessage}</Text> : null}
        <Text type="secondary" className="inbox-row-meta">AI：{analysisLine}</Text>
        <StatusBadge status={analysisStatusCode ?? undefined} label={analysisStatus} />
      </div>
      <Space>
        <Button type="primary" onClick={onRead} disabled={!canRead} aria-label="阅读摘要">
          阅读摘要
        </Button>
        {onMore ? <Button onClick={onMore} aria-label="查看技术详情">更多</Button> : null}
      </Space>
    </div>
  )
}
