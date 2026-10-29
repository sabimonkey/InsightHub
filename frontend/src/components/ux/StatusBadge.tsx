import { Tag } from 'antd'

const MAP: Record<string, { color: string; label: string }> = {
  SUCCEEDED: { color: 'success', label: '已完成' },
  PARTIAL: { color: 'warning', label: '部分完成' },
  FAILED: { color: 'error', label: '失败' },
  RUNNING: { color: 'processing', label: '分析中' },
  PENDING: { color: 'default', label: '等待中' },
  QUEUED: { color: 'default', label: '等待中' },
  未分析: { color: 'default', label: '未分析' },
}

export function StatusBadge({ status, label }: { status?: string | null; label?: string | null }) {
  const key = label || status || '—'
  const mapped = MAP[status || ''] || MAP[key] || { color: 'default', label: key }
  return <Tag color={mapped.color}>{mapped.label}</Tag>
}
