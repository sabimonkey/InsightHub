import { Button, Descriptions, Modal, Space, Table, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { fetchCoverQueue, retryCoverRun, type CoverQueueJob, type CoverQueueSummary } from '../../api'

const { Text } = Typography

type Props = {
  open: boolean
  onClose: () => void
}

export function CoverQueueModal({ open, onClose }: Props) {
  const [summary, setSummary] = useState<CoverQueueSummary | null>(null)
  const [jobs, setJobs] = useState<CoverQueueJob[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<CoverQueueJob | null>(null)
  const [retrying, setRetrying] = useState(false)

  const reload = useCallback(() => {
    setLoading(true)
    void fetchCoverQueue()
      .then((body) => {
        if (body.ok) {
          setSummary(body.summary ?? null)
          setJobs(body.jobs ?? [])
        }
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (open) reload()
  }, [open, reload])

  async function handleRetry(row: CoverQueueJob) {
    setRetrying(true)
    try {
      const body = await retryCoverRun(row.run_id)
      if (!body.ok) {
        message.error(body.message || body.code || '重试失败')
        return
      }
      message.success('已重新提交配图任务')
      setDetail(null)
      reload()
    } finally {
      setRetrying(false)
    }
  }

  return (
    <>
      <Modal
        title="配图任务队列"
        open={open}
        onCancel={onClose}
        width={880}
        footer={[
          <Button key="refresh" onClick={reload} loading={loading}>
            刷新
          </Button>,
          <Button key="close" type="primary" onClick={onClose}>
            关闭
          </Button>,
        ]}
      >
        {summary ? (
          <p>
            <Text>
              活动 {summary.active} · 排队 {summary.queued} · 执行中 {summary.generating} · 成功 {summary.succeeded} · 失败{' '}
                {summary.failed} · 本月项目配图尝试 {summary.monthly_attempts ?? summary.monthly_used} / InsightHub 本地安全上限 {summary.monthly_budget} · 自动配图{' '}
              {summary.auto_enabled ? '开' : '关'}
            </Text>
          </p>
        ) : null}
        <Table
          size="small"
          rowKey="run_id"
          loading={loading}
          pagination={{ pageSize: 10 }}
          dataSource={jobs}
          onRow={(row) => ({
            onClick: () => setDetail(row),
            style: { cursor: 'pointer' },
          })}
          columns={[
            { title: '资料', dataIndex: 'source_title', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 100 },
            {
              title: '结果',
              width: 88,
              render: (_, row) => (row.is_active ? '进行中' : row.terminal_success ? '可用' : '失败'),
            },
            { title: '错误', dataIndex: 'error_message', ellipsis: true },
            { title: '更新', dataIndex: 'updated_at', width: 180 },
          ]}
        />
      </Modal>
      <Modal
        title="配图任务详情"
        open={detail != null}
        onCancel={() => setDetail(null)}
        footer={
          detail ? (
            <Space>
              <a href={`/library?source=${detail.source_id}`} target="_blank" rel="noreferrer">
                查看资料
              </a>
              {detail.can_retry ? (
                <Button type="primary" loading={retrying} onClick={() => void handleRetry(detail)}>
                  重新生成
                </Button>
              ) : null}
              <Button onClick={() => setDetail(null)}>关闭</Button>
            </Space>
          ) : null
        }
      >
        {detail ? (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="资料">{detail.source_title}</Descriptions.Item>
            <Descriptions.Item label="Source ID">{detail.source_id}</Descriptions.Item>
            <Descriptions.Item label="Run ID">{detail.run_id}</Descriptions.Item>
            <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
            <Descriptions.Item label="阶段">{detail.stage}</Descriptions.Item>
            <Descriptions.Item label="错误码">{detail.error_code || '—'}</Descriptions.Item>
            <Descriptions.Item label="说明">{detail.error_message || '—'}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{detail.updated_at || '—'}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>
    </>
  )
}
