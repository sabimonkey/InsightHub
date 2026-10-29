import { Alert, Button, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { fetchInbox } from '../api'
import type { InboxItem } from '../types'
import { AddSourcePanel } from '../components/AddSourcePanel'
import { PageHeader } from '../components/ux/PageHeader'
import { RecentSourceRow } from '../components/ux/RecentSourceRow'
import { EmptyState } from '../components/ux/EmptyState'

const { Text } = Typography
const RECENT_LIMIT = 5
const POLL_MS = 8000

type InboxPageProps = {
  onOpenLibrary?: (sourceId: string) => void
  onViewAllLibrary?: () => void
}

export function InboxPage({ onOpenLibrary, onViewAllLibrary }: InboxPageProps) {
  const [items, setItems] = useState<InboxItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const loadRecent = useCallback(() => {
    setError(null)
    return fetchInbox('all', 1, RECENT_LIMIT)
      .then((body) => {
        const rows = body.items.filter((row) => row.source_id)
        setItems(rows.slice(0, RECENT_LIMIT))
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : '加载失败')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    void loadRecent()
  }, [loadRecent])

  useEffect(() => {
    const pending = items.some(
      (row) =>
        row.extraction_status_code === 'PENDING' ||
        row.extraction_status_code === 'RUNNING' ||
        row.analysis_status_code === 'PENDING' ||
        row.analysis_status_code === 'QUEUED' ||
        row.analysis_status_code === 'RUNNING',
    )
    if (!pending) return
    const timer = window.setInterval(() => void loadRecent(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [items, loadRecent])

  return (
    <main className="app-page inbox-page collection-capture-page">
      <PageHeader title="收集资料" description="添加网页、文本或文件，InsightHub 将自动提取和整理资料。" />
      <div className="collection-capture-center">
        <AddSourcePanel
          variant="centered"
          onAdded={() => {
            setLoading(true)
            void loadRecent()
          }}
        />
      </div>
      <section className="recent-sources-section" aria-label="最近收集">
        <div className="recent-sources-header">
          <Text strong>最近收集</Text>
          <Button type="link" onClick={() => onViewAllLibrary?.()} aria-label="查看全部资料">
            查看全部 →
          </Button>
        </div>
        {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 12 }} /> : null}
        {loading ? <Text type="secondary">加载中…</Text> : null}
        {!loading && items.length === 0 ? (
          <EmptyState title="最近还没有收集记录" hint="添加第一条资料即可开始。" />
        ) : null}
        <div className="recent-sources-list">
          {items.map((record) =>
            record.source_id ? (
              <RecentSourceRow
                key={record.source_id}
                record={record}
                onClick={() => onOpenLibrary?.(record.source_id!)}
              />
            ) : null,
          )}
        </div>
      </section>
    </main>
  )
}
