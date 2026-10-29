import { Button, Descriptions, Modal, Select, Space, Table, Typography, message } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchAnalysisQueue, type AnalysisQueueJob, type AnalysisQueueSummary } from '../../api'

const { Text } = Typography

async function reanalyzeSource(sourceId: string): Promise<{ ok: boolean; message?: string }> {
  const response = await fetch(`/api/sources/${sourceId}/reanalyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: { message?: string }; message?: string }
    return { ok: false, message: body.detail?.message || body.message || '重新分析失败' }
  }
  return { ok: true }
}

type Props = {
  open: boolean
  onClose: () => void
}

export function AnalysisQueueModal({ open, onClose }: Props) {
  const [summary, setSummary] = useState<AnalysisQueueSummary | null>(null)
  const [jobs, setJobs] = useState<AnalysisQueueJob[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<AnalysisQueueJob | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | 'ALL'>('ALL')
  const [errorFilter, setErrorFilter] = useState<'ALL' | '503'>('ALL')

  const filteredJobs = useMemo(() => {
    return jobs.filter((row) => {
      if (statusFilter !== 'ALL' && row.status !== statusFilter) return false
      if (errorFilter === '503') {
        const hay = `${row.error_code ?? ''} ${row.error_message ?? ''}`
        if (!hay.includes('503') && !hay.includes('OVERLOADED')) return false
      }
      return true
    })
  }, [jobs, statusFilter, errorFilter])

  const reload = useCallback(() => {
    setLoading(true)
    void fetchAnalysisQueue()
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

  return (
    <>
      <Modal
        title="AI 分析任务队列"
        open={open}
        onCancel={onClose}
        width={920}
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
              活动 {summary.active} · 等待 {summary.pending} · 分析中 {summary.running} · 成功 {summary.succeeded} · 部分{' '}
              {summary.partial} · 失败 {summary.failed}
            </Text>
          </p>
        ) : null}
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            size="small"
            style={{ width: 120 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'ALL', label: '全部状态' },
              { value: 'PENDING', label: '等待' },
              { value: 'RUNNING', label: '分析中' },
              { value: 'SUCCEEDED', label: '成功' },
              { value: 'PARTIAL', label: '部分' },
              { value: 'FAILED', label: '失败' },
            ]}
          />
          <Select
            size="small"
            style={{ width: 140 }}
            value={errorFilter}
            onChange={setErrorFilter}
            options={[
              { value: 'ALL', label: '全部错误' },
              { value: '503', label: '503 / 过载' },
            ]}
          />
        </Space>
        <Table
          size="small"
          rowKey="run_id"
          loading={loading}
          pagination={{ pageSize: 10 }}
          dataSource={filteredJobs}
          onRow={(row) => ({
            onClick: () => setDetail(row),
            style: { cursor: 'pointer' },
          })}
          columns={[
            { title: '资料', dataIndex: 'source_title', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 88 },
            { title: '阶段', dataIndex: 'stage_label', ellipsis: true, width: 160 },
            {
              title: '模型',
              dataIndex: 'model_name',
              ellipsis: true,
              width: 180,
              render: (value: string, row: AnalysisQueueJob) => row.is_simulated ? `模拟测试 · ${value}` : value,
            },
            {
              title: '错误 / 历史提示',
              dataIndex: 'error_message',
              ellipsis: true,
              render: (value: string | null, row: AnalysisQueueJob) => value && ['SUCCEEDED', 'PARTIAL'].includes(row.status)
                ? `历史告警（任务现为${row.status}）：${value}`
                : value || '—',
            },
          ]}
        />
      </Modal>
      <Modal
        title="分析任务详情"
        open={detail != null}
        onCancel={() => setDetail(null)}
        footer={
          detail ? (
            <Space>
              <a href={`/library?source=${detail.source_id}`} target="_blank" rel="noreferrer">
                查看资料
              </a>
              {detail.can_retry ? (
                <Button
                  type="primary"
                  loading={retrying}
                  onClick={() => {
                    setRetrying(true)
                    void reanalyzeSource(detail.source_id)
                      .then((body) => {
                        if (!body.ok) message.error(body.message || '重新分析失败')
                        else {
                          message.success('已提交重新分析')
                          setDetail(null)
                          reload()
                        }
                      })
                      .finally(() => setRetrying(false))
                  }}
                >
                  重新分析
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
            <Descriptions.Item label="阶段">{detail.stage_label}</Descriptions.Item>
            <Descriptions.Item label="模型">{detail.is_simulated ? `模拟测试（未调用真实模型） · ${detail.model_name}` : detail.model_name}</Descriptions.Item>
            <Descriptions.Item label={['SUCCEEDED', 'PARTIAL'].includes(detail.status) ? '历史告警' : '当前错误'}>{detail.error_message || '—'}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>
    </>
  )
}
