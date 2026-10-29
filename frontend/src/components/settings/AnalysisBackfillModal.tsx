import { Alert, Button, Modal, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { fetchAnalysisBackfillPreview, startAnalysisBackfill, type AnalysisBackfillPreview } from '../../api'

const { Text, Paragraph } = Typography

const BUCKET_LABELS: Record<string, string> = {
  ready: '已成功，默认跳过',
  not_analyzed: '从未分析（正文已就绪）',
  analysis_failed: '分析失败，可重试',
  analysis_partial: '部分成功',
  in_progress: '已有活动任务',
  extraction: '正文提取未就绪',
  extraction_not_ready: '正文未就绪，无法分析',
}

type Props = {
  open: boolean
  onClose: () => void
  onStarted?: () => void
}

export function AnalysisBackfillModal({ open, onClose, onStarted }: Props) {
  const [preview, setPreview] = useState<AnalysisBackfillPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [resultNote, setResultNote] = useState<string | null>(null)

  const reload = useCallback(() => {
    setLoading(true)
    setError(null)
    void fetchAnalysisBackfillPreview()
      .then((body) => {
        if (body.ok !== false) setPreview(body)
        else setError(body.message || body.code || '无法加载候选统计')
      })
      .catch(() => setError('无法加载候选统计'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (open) {
      setResultNote(null)
      reload()
    }
  }, [open, reload])

  async function confirmStart(mode: 'fresh' | 'retry_failed') {
    setStarting(true)
    setError(null)
    try {
      const body = await startAnalysisBackfill({ confirm: true, mode })
      if (!body.ok) {
        setError(body.message || body.code || '启动失败')
        return
      }
      const n = body.enqueued_run_ids?.length ?? 0
      const skipped = body.skipped ? Object.entries(body.skipped).map(([k, v]) => `${k}:${v}`).join(' ') : ''
      setResultNote(`已提交 ${n} 条分析任务。${skipped ? `跳过：${skipped}` : ''}`.trim())
      onStarted?.()
      reload()
    } catch {
      setError('启动失败')
    } finally {
      setStarting(false)
    }
  }

  return (
    <Modal
      title="批量 AI 分析"
      open={open}
      onCancel={onClose}
      width={680}
      footer={[
        <Button key="refresh" onClick={reload} loading={loading}>
          刷新统计
        </Button>,
        <Button key="close" onClick={onClose}>
          关闭
        </Button>,
        <Button
          key="retry"
          loading={starting}
          disabled={!(preview?.retry_failed_count ?? 0)}
          onClick={() => void confirmStart('retry_failed')}
        >
          重试失败（{preview?.retry_failed_count ?? 0}）
        </Button>,
        <Button
          key="start"
          type="primary"
          loading={starting}
          disabled={!(preview?.fresh_candidate_count ?? preview?.default_candidate_count ?? 0)}
          onClick={() => void confirmStart('fresh')}
        >
          分析未分析（{preview?.fresh_candidate_count ?? preview?.default_candidate_count ?? 0}）
        </Button>,
      ]}
    >
      {error ? <Alert type="error" message={error} style={{ marginBottom: 12 }} /> : null}
      {resultNote ? <Alert type="success" message={resultNote} style={{ marginBottom: 12 }} /> : null}
      {preview?.explanation ? <Alert type="info" message={preview.explanation} style={{ marginBottom: 12 }} /> : null}
      {preview?.cover_side_effect ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="自动配图已开启"
          description={`本月已用 ${preview.cover_side_effect.monthly_used}/${preview.cover_side_effect.monthly_budget}。${preview.cover_side_effect.note}`}
        />
      ) : null}
      <Paragraph>
        <Text strong>
          活动任务 {preview?.active_task_count ?? 0} · 未分析 {preview?.fresh_candidate_count ?? 0} · 可重试失败{' '}
          {preview?.retry_failed_count ?? 0} · 部分成功 {preview?.retry_partial_count ?? 0}
        </Text>
      </Paragraph>
      {preview?.buckets
        ? Object.entries(preview.buckets).map(([key, value]) => (
            <div key={key} style={{ marginBottom: 6 }}>
              <Text>
                {BUCKET_LABELS[key] ?? key}：{value.count}
              </Text>
            </div>
          ))
        : null}
    </Modal>
  )
}
