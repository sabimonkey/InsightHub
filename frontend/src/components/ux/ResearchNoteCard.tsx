import { Button, Card, Space, Typography } from 'antd'
import { StatusBadge } from './StatusBadge'

const { Text, Paragraph } = Typography

export type ResearchNoteCardData = {
  sourceId: string
  title: string
  sourceType?: string | null
  summarySnippet?: string | null
  analysisStatus?: string | null
  analysisStatusCode?: string | null
  collectedAt?: string | null
  originalUrl?: string | null
  categories?: string[]
  topics?: string[]
  pipelineStatus?: string | null
}

type Props = {
  item: ResearchNoteCardData
  onRead: (sourceId: string) => void
  onOriginal?: (url: string) => void
  onDetail?: (sourceId: string) => void
}

export function ResearchNoteCard({ item, onRead, onOriginal, onDetail }: Props) {
  const url = item.originalUrl
  return (
    <Card size="small" style={{ marginBottom: 12 }} aria-label="资料卡片">
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space wrap>
          <Text strong style={{ cursor: onDetail ? 'pointer' : undefined }} onClick={() => onDetail?.(item.sourceId)}>{item.title}</Text>
          {item.sourceType ? <Text type="secondary">{item.sourceType}</Text> : null}
          <StatusBadge status={item.analysisStatusCode ?? undefined} label={item.analysisStatus} />
        </Space>
        {item.summarySnippet ? <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>{item.summarySnippet}</Paragraph> : null}
        {item.collectedAt ? <Text type="secondary">收藏于 {new Date(item.collectedAt).toLocaleString()}</Text> : null}
        {item.pipelineStatus ? <Text type="secondary">提取：{item.pipelineStatus}</Text> : null}
        {url ? (
          <a className="url-ellipsis" href={url} target="_blank" rel="noreferrer" title={url}>
            {url}
          </a>
        ) : null}
        <Space>
          <Button type="primary" onClick={() => onRead(item.sourceId)}>阅读摘要</Button>
          {url && onOriginal ? <Button onClick={() => onOriginal(url)}>查看原文</Button> : null}
        </Space>
      </Space>
    </Card>
  )
}
