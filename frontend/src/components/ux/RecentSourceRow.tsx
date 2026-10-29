import { RightOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import type { InboxItem } from '../../types'

const { Text } = Typography

function compactStatus(record: InboxItem): string {
  if (record.extraction_status_code === 'FAILED' || record.extraction_status_code === 'WORKER_NOT_CONSUMING') {
    if (record.extraction_user_message) {
      return record.extraction_status_label ?? '正文提取失败'
    }
    return record.extraction_status_label ?? '正文提取失败'
  }
  if (record.extraction_status_code === 'PENDING' || record.extraction_status_code === 'RUNNING') {
    return record.extraction_status_label ?? '正在提取正文'
  }
  if (record.analysis_status) {
    return record.analysis_status
  }
  return '尚未分析'
}

type Props = {
  record: InboxItem
  onClick: () => void
}

export function RecentSourceRow({ record, onClick }: Props) {
  const title = record.title || record.display_name || '未命名'
  const when = record.collected_at ? new Date(record.collected_at).toLocaleString() : '—'
  return (
    <button type="button" className="recent-source-row" onClick={onClick} aria-label={`最近资料：${title}`}>
      <div className="recent-source-row-main">
        <Text strong className="recent-source-row-title">{title}</Text>
        <Text type="secondary" className="recent-source-row-meta">
          {when} · {compactStatus(record)}
        </Text>
      </div>
      <RightOutlined aria-hidden />
    </button>
  )
}
