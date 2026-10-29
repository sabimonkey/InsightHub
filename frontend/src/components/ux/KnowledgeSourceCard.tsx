import { Button, Dropdown, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { KnowledgeCover } from './KnowledgeCover'

const { Text } = Typography

export type KnowledgeCardItem = {
  sourceId: string
  title: string
  titleFull?: string | null
  sourceType?: string | null
  collectedAt?: string | null
  analysisStatus?: string | null
  analysisStatusCode?: string | null
  extractionStatusLabel?: string | null
  previewImageUrl?: string | null
  coverOrigin?: string | null
  categories?: string[]
  supportsTextSupplement?: boolean
}

type Props = {
  item: KnowledgeCardItem
  onOpen: (sourceId: string) => void
  onOpenDetail?: (sourceId: string) => void
  onGenerateCover?: (sourceId: string) => void
  onSupplement?: (sourceId: string) => void
  onDelete?: (sourceId: string) => void
  highlighted?: boolean
}

function statusLine(item: KnowledgeCardItem): string {
  const parts: string[] = []
  if (item.extractionStatusLabel) parts.push(item.extractionStatusLabel)
  if (item.analysisStatus) parts.push(item.analysisStatus)
  return parts.join(' · ') || '尚未分析'
}

export function KnowledgeSourceCard({ item, onOpen, onOpenDetail, onGenerateCover, onSupplement, onDelete, highlighted }: Props) {
  const when = item.collectedAt ? new Date(item.collectedAt).toLocaleDateString() : null
  const menuItems: MenuProps['items'] = []
  if (onOpenDetail) {
    menuItems.push({ key: 'detail', label: '查看详情', onClick: () => onOpenDetail(item.sourceId) })
  }
  if (onGenerateCover) {
    menuItems.push({
      key: 'cover',
      label: item.previewImageUrl && item.coverOrigin === 'generated' ? '重新生成封面' : '生成封面',
      onClick: () => onGenerateCover(item.sourceId),
    })
  }
  if (onSupplement && item.supportsTextSupplement) {
    menuItems.push({ key: 'supplement', label: '补充 X 原文', onClick: () => onSupplement(item.sourceId) })
  }
  if (onDelete) {
    menuItems.push({ key: 'delete', label: '删除资料', danger: true, onClick: () => onDelete(item.sourceId) })
  }

  return (
    <article
      className={`knowledge-card${highlighted ? ' knowledge-card--highlight' : ''}`}
      data-source-id={item.sourceId}
      role="button"
      tabIndex={0}
      aria-label={`资料卡片：${item.title}`}
      onClick={() => onOpen(item.sourceId)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen(item.sourceId)
        }
      }}
    >
      <div className="knowledge-card-media">
        <KnowledgeCover
          sourceId={item.sourceId}
          previewImageUrl={item.previewImageUrl}
          coverOrigin={item.coverOrigin}
          sourceType={item.sourceType}
          categories={item.categories}
          title={item.title}
        />
      </div>
      <div className="knowledge-card-body">
        <Text strong className="knowledge-card-title" title={item.titleFull || item.title}>
          {item.title}
        </Text>
        <Text type="secondary" className="knowledge-card-meta">
          {[item.sourceType, when].filter(Boolean).join(' · ')}
        </Text>
        <Text type="secondary" className="knowledge-card-status">{statusLine(item)}</Text>
        <div
          className="knowledge-card-actions"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          {menuItems.length ? (
            <Dropdown menu={{ items: menuItems }} trigger={['click']}>
              <Button size="small" aria-label="更多操作">
                更多
              </Button>
            </Dropdown>
          ) : null}
        </div>
      </div>
    </article>
  )
}
